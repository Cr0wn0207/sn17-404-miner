"""Deterministic search; independent initial drafts run concurrently.

Request IDs, ordering, budget decisions and output bytes depend exclusively on
committed source, seed, frozen image, witnessed responses and verified previews.
Transport/provider failures propagate to the runtime's capture recovery.
"""

import asyncio
import base64
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from renderer_client import RenderOptions, RenderRejected

from . import prompts
from .budget import LIMIT, Budget, charge, input_bound

SOL = "gpt-6.1-sol"
ASTRA = "gpt-6-astra"
FRONT = RenderOptions(thetas=(30, 330, 0, 0), phis=(0, 0, 15, -30), img_size=384, bg_color="ffffff", lighting="neutral")
GRAY = RenderOptions(thetas=(30, 330, 0, 0), phis=(0, 0, 15, -30), img_size=256, bg_color="808080", lighting="neutral")
SIDES = RenderOptions(
    thetas=(90, 180, 270, 0), phis=(0, 0, 0, -90), img_size=256, bg_color="ffffff", lighting="neutral"
)
WRAPPER = Path(__file__).with_name("normalize.js").read_text()


def png_url(data):
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def bounded_png(data, size=1152):
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=False, compress_level=6)
        return out.getvalue()


def normalize(raw, yaw=0):
    source = raw.strip()
    fence = re.fullmatch(r"```(?:javascript|js|mjs)?\s*\n([\s\S]*?)\n```", source)
    if fence:
        source = fence[1].strip()
    # Require the promised shape. Preserve helper declarations at module scope.
    match = re.match(r"export\s+default\s+(?=function\b)", source)
    if match is None or "__r3Build" in source:
        raise ValueError("Expected a default synchronous function first")
    return (
        "const __r3Build = "
        + source[match.end() :]
        + "\n;\n"
        + WRAPPER.replace("__R3_YAW__", format(float(yaw), ".12g"))
    )


def contact_sheet(front, gray, sides):
    sheet = Image.new("RGB", (1152, 768), "white")
    for data, box in ((front, (0, 0, 768, 768)), (gray, (768, 0, 1152, 384)), (sides, (768, 384, 1152, 768))):
        with Image.open(io.BytesIO(data)) as image:
            panel = image.convert("RGB").resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS)
            sheet.paste(panel, box[:2])
    out = io.BytesIO()
    sheet.save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


@dataclass(frozen=True)
class Candidate:
    source: str
    sheet: bytes
    raw: str


class Search:
    def __init__(self, image, seed, witness):
        self.image = bounded_png(image)
        self.seed = seed
        self.identity = hashlib.sha256(image).hexdigest()
        self.witness = witness
        self.budget = Budget()
        self.brief = "Reconstruct the target's seven most distinctive visual features."

    async def call(self, ident, model, instructions, content, outputs, *, schema=None, reserve=0, effort="high"):
        estimate = input_bound(instructions, content, schema)
        if not self.budget.allows(model, estimate, outputs, reserve):
            return None
        params = {
            "request_id": ident,
            "model": model,
            "instructions": instructions,
            "input": [{"role": "user", "content": content}],
            "store": False,
            "service_tier": "default",
            "reasoning": {"effort": effort},
            "max_output_tokens": outputs,
        }
        if schema:
            params["text"] = {
                "format": {"type": "json_schema", "name": "visual_scores", "strict": True, "schema": schema}
            }
        # Do not catch provider/transport errors: silently changing the program
        # after a failed exchange would diverge from a replay of successful calls.
        result = await self.witness.responses.create(**params)
        self.budget.consume(model, result)
        if result.status != "completed" or not result.output_text:
            return None
        return result.output_text.strip()

    def target(self):
        return [
            {"type": "input_text", "text": "REFERENCE IMAGE:"},
            {"type": "input_image", "image_url": png_url(self.image), "detail": "high"},
        ]

    async def render(self, raw, yaw=0):
        source = normalize(raw, yaw)
        front = await self.witness.render(source, FRONT)
        gray = await self.witness.render(source, GRAY)
        sides = await self.witness.render(source, SIDES)
        return Candidate(source, contact_sheet(front, gray, sides), raw)

    async def build(self, ident, *, model=SOL, strategy="", parent=None, feedback="", reserve=500000):
        content = self.target()
        text = "Construction brief:\n" + self.brief + "\nApproach: " + strategy
        if parent:
            text += (
                "\nImprove the following candidate, preserving its successful features. "
                "Return the complete module. Fix the largest visible errors before small details.\n"
                "Specific corrections:\n" + feedback + "\nCurrent module:\n" + parent.raw
            )
            content.append({"type": "input_image", "image_url": png_url(parent.sheet), "detail": "high"})
        content.append({"type": "input_text", "text": text})
        raw = await self.call(ident, model, prompts.BUILD, content, 24576, reserve=reserve)
        if raw is None:
            return None
        try:
            return await self.render(raw)
        except (RenderRejected, ValueError) as error:
            # Only reproducible validation rejections or source-shape errors are
            # eligible for one bounded repair. Infrastructure failures propagate.
            detail = error.detail_json if isinstance(error, RenderRejected) else str(error)
            content.append(
                {
                    "type": "input_text",
                    "text": "Repair this module. Preserve likeness.\n" + raw + "\nExact rejection:\n" + detail,
                }
            )
            repair = await self.call(ident + 10000, SOL, prompts.BUILD, content, 24576, reserve=reserve)
            if repair is None:
                return None
            try:
                return await self.render(repair)
            except (RenderRejected, ValueError):
                return None

    async def initials(self):
        # Reserve the WHOLE stage before dispatch. No response arrival order can
        # change how many requests are admitted or how their usage is settled.
        requests = []
        reserved = 0
        for i, strategy in enumerate(prompts.STRATEGIES):
            content = self.target() + [
                {"type": "input_text", "text": "Construction brief:\n" + self.brief + "\nApproach: " + strategy}
            ]
            upper = charge(SOL, input_bound(prompts.BUILD, content), 24576)
            if (
                self.budget.spent + reserved + upper + 1800000 > LIMIT - 100000
                or self.budget.calls + len(requests) + 1 > 60
            ):
                break
            requests.append(
                {
                    "request_id": 10 + i,
                    "model": SOL,
                    "instructions": prompts.BUILD,
                    "input": [{"role": "user", "content": content}],
                    "store": False,
                    "service_tier": "default",
                    "reasoning": {"effort": "high"},
                    "max_output_tokens": 24576,
                }
            )
            reserved += upper
        results = await asyncio.gather(*(self.witness.responses.create(**r) for r in requests), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
            self.budget.consume(SOL, result)
        candidates = []
        for request, result in zip(requests, results):
            if result.status != "completed" or not result.output_text:
                continue
            raw = result.output_text.strip()
            try:
                candidate = await self.render(raw)
            except (RenderRejected, ValueError) as error:
                detail = error.detail_json if isinstance(error, RenderRejected) else str(error)
                content = list(request["input"][0]["content"])
                content.append(
                    {
                        "type": "input_text",
                        "text": "Repair this module. Preserve likeness.\n" + raw + "\nExact rejection:\n" + detail,
                    }
                )
                repaired = await self.call(
                    request["request_id"] + 10000, SOL, prompts.BUILD, content, 24576, reserve=1800000
                )
                if not repaired:
                    continue
                try:
                    candidate = await self.render(repaired)
                except (RenderRejected, ValueError):
                    continue
            candidates.append(candidate)
        return candidates

    async def select(self, candidates, ident, *, mirror=True):
        # The first candidate is the incumbent and wins close/noisy comparisons.
        candidates = list({c.source: c for c in candidates if c is not None}.values())
        if not candidates:
            return None, ""
        if len(candidates) == 1:
            return candidates[0], ""
        indices = list(range(len(candidates)))
        indices.sort(key=lambda i: hashlib.sha256(f"{self.seed}:{self.identity}:{ident}:{i}".encode()).digest())
        scores = {i: [] for i in indices}
        notes = {i: [] for i in indices}
        for order_index in range(2 if mirror else 1):
            order = indices if order_index == 0 else list(reversed(indices))
            labels = {chr(65 + j): i for j, i in enumerate(order)}
            content = self.target()
            content.append({"type": "input_text", "text": "Construction brief:\n" + self.brief})
            for label, i in labels.items():
                content.extend(
                    [
                        {"type": "input_text", "text": "CANDIDATE " + label},
                        {"type": "input_image", "image_url": png_url(candidates[i].sheet), "detail": "high"},
                    ]
                )
            raw = await self.call(
                ident + order_index,
                SOL,
                prompts.JUDGE,
                content,
                4096,
                schema=score_schema(list(labels)),
                effort="medium",
            )
            if raw is None:
                continue
            try:
                rows = parse_scores(raw, labels)
            except (ValueError, KeyError, TypeError):
                continue
            for row in rows:
                i = labels[row["label"]]
                scores[i].append(score(row))
                notes[i].append(row["fixes"])
        # Require every candidate to have the same number of valid votes.
        counts = [len(scores[i]) for i in indices]
        if not counts or not min(counts) or len(set(counts)) != 1:
            return candidates[0], ""
        means = {i: sum(scores[i]) / len(scores[i]) for i in indices}
        winner = 0
        for i in range(1, len(candidates)):
            # In AB/BA, demand agreement over the incumbent as well as a useful
            # mean gain; a position-sensitive win cannot replace a good parent.
            if means[i] < means[winner] - 0.18 and all(a <= b + 0.1 for a, b in zip(scores[i], scores[winner])):
                winner = i
        return candidates[winner], "\n".join(notes[winner])


def score_schema(labels):
    integer = lambda lo, hi: {"type": "integer", "minimum": lo, "maximum": hi}
    return {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "enum": labels},
                        "front": {
                            "type": "array",
                            "items": {"type": "number", "minimum": 0, "maximum": 10},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                        "feature_hits": integer(0, 7),
                        "artifact": {"type": "number", "minimum": 0, "maximum": 10},
                        "bad_sides": integer(0, 4),
                        "fixes": {"type": "string"},
                    },
                    "required": ["label", "front", "feature_hits", "artifact", "bad_sides", "fixes"],
                    "additionalProperties": False,
                },
                "minItems": len(labels),
                "maxItems": len(labels),
            }
        },
        "required": ["scores"],
        "additionalProperties": False,
    }


def parse_scores(raw, labels):
    rows = json.loads(raw)["scores"]
    if len(rows) != len(labels) or {r["label"] for r in rows} != set(labels):
        raise ValueError("Incomplete or duplicate candidate labels")
    for r in rows:
        if not isinstance(r["fixes"], str) or len(r["front"]) != 4:
            raise ValueError("Invalid critique")
        for value in [*r["front"], r["artifact"]]:
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10:
                raise ValueError("Invalid penalty")
        for key, maximum in (("feature_hits", 7), ("bad_sides", 4)):
            if type(r[key]) is not int or not 0 <= r[key] <= maximum:
                raise ValueError("Invalid feature/side count")
    return rows


def score(row):
    return (
        0.70 * sum(row["front"]) / 4
        + 0.20 * (7 - row["feature_hits"]) * 10 / 7
        + 0.10 * row["artifact"]
        + (2 if row["bad_sides"] >= 3 else 0)
    )


async def generate(image, seed, witness):
    search = Search(image, seed, witness)
    brief = await search.call(1, SOL, prompts.PLAN, search.target(), 4096, reserve=3500000, effort="medium")
    if brief:
        search.brief = brief
    candidates = await search.initials()
    winner, feedback = await search.select(candidates, 100)
    if winner is None:
        return None
    original = winner
    # Spend the strongest model on improving an already rendered reconstruction.
    improved = await search.build(
        200,
        model=ASTRA,
        parent=winner,
        feedback=feedback,
        strategy="Correct silhouette and identity before polishing.",
        reserve=700000,
    )
    if improved is None:
        improved = await search.build(201, parent=winner, feedback=feedback, reserve=700000)
    winner, feedback = await search.select([winner, improved], 210)
    refined = []
    for ident, strategy in (
        (300, "Correct the two largest proportion or shape errors; preserve identity."),
        (301, "Improve the seven key details, curves and surface colors without losing proportions."),
    ):
        candidate = await search.build(ident, parent=winner, feedback=feedback, strategy=strategy, reserve=400000)
        if candidate:
            refined.append(candidate)
    winner, _ = await search.select([winner, *refined, original], 400)
    # This is exactly the source that was rendered, not a post-selection rewrite.
    return winner.source
