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

from PIL import Image, ImageChops
from renderer_client import RenderOptions, RenderRejected

from . import alignment, prompts
from .budget import LIMIT, Budget, charge, input_bound
from .surgery import PATCH_SCHEMA, apply_edits

SOL = "gpt-6.1-sol"
ASTRA = "gpt-6-astra"
FRONT = RenderOptions(thetas=(30, 330, 0, 0), phis=(0, 0, 15, -30), img_size=768, gap=0, bg_color="ffffff", lighting="neutral")
GRAY = RenderOptions(thetas=(30, 330, 0, 0), phis=(0, 0, 15, -30), img_size=384, gap=0, bg_color="808080", lighting="neutral")
SIDES = RenderOptions(
    thetas=(90, 180, 270, 0), phis=(0, 0, 0, -90), img_size=384, gap=0, bg_color="ffffff", lighting="neutral"
)
POSE_PROBE = RenderOptions(thetas=(30, 330, 0, 0), phis=(0, 0, 15, -30),
                           img_size=192, gap=0, bg_color="ffffff", lighting="neutral")
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


def normalize(raw, yaw=0, pitch=0, stretch=(1, 1, 1)):
    source = raw.strip()
    fence = re.fullmatch(r"```(?:javascript|js|mjs)?\s*\n([\s\S]*?)\n```", source)
    if fence:
        source = fence[1].strip()
    # Require the promised shape. Preserve helper declarations at module scope.
    match = re.match(r"export\s+default\s+(?=function\b)", source)
    if match is None or "__r3Build" in source:
        raise ValueError("Expected a default synchronous function first")
    stretch = tuple(float(v) for v in stretch)
    if len(stretch) != 3 or not all(math.isfinite(v) and v > 0 for v in stretch):
        raise ValueError("Expected three finite positive dimension factors")
    wrapper = WRAPPER
    if pitch:
        # An explicit pose candidate must actually rotate, including when the
        # food, handle or garnish makes the complete object taller than .5 W.
        wrapper = wrapper.replace("if (dimensions.y < 0.5 * Math.max(dimensions.x, dimensions.z)) {", "{")
    if stretch != (1, 1, 1):
        factors = ", ".join(format(v, ".12g") for v in stretch)
        wrapper = wrapper.replace("  oriented.rotation.y =", "  oriented.scale.set(" + factors + ");\n  oriented.rotation.y =", 1)
    return (
        "const __r3Build = "
        + source[match.end() :]
        + "\n;\n"
        + wrapper.replace("__R3_YAW__", format(float(yaw), ".12g")).replace("__R3_PITCH__", format(float(pitch), ".12g"))
    )


def front_closeups(data):
    """Enlarge each original front view independently; never change geometry."""
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        output = Image.new("RGB", (1152, 1152), "white")
        for index in range(4):
            x, y = index % 2, index // 2
            tile = image.crop((x * image.width // 2, y * image.height // 2,
                               (x + 1) * image.width // 2, (y + 1) * image.height // 2))
            difference = ImageChops.difference(tile, Image.new("RGB", tile.size, "white"))
            channels = difference.split()
            mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            box = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
            if box:
                margin = max(4, math.ceil(0.07 * max(box[2] - box[0], box[3] - box[1])))
                box = (max(0, box[0] - margin), max(0, box[1] - margin),
                       min(tile.width, box[2] + margin), min(tile.height, box[3] + margin))
                tile = tile.crop(box)
            tile.thumbnail((560, 560), Image.Resampling.LANCZOS)
            output.paste(tile, (x * 576 + (576 - tile.width) // 2, y * 576 + (576 - tile.height) // 2))
        out = io.BytesIO()
        output.save(out, format="PNG", optimize=False, compress_level=6)
        return out.getvalue()


def jpeg_url(data):
    with Image.open(io.BytesIO(data)) as image:
        out = io.BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=92, subsampling=0)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


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
    lineage: int = 0
    detail: bytes = b""
    pitch: float = 0
    stretch: tuple = (1, 1, 1)
    yaw: float = 0


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

    def target(self, *, compressed=False):
        return [
            {"type": "input_text", "text": "REFERENCE IMAGE:"},
            {"type": "input_image", "image_url": (jpeg_url if compressed else png_url)(self.image), "detail": "high"},
        ]

    async def render(self, raw, yaw=0, pitch=0, lineage=0, stretch=(1, 1, 1)):
        source = normalize(raw, yaw, pitch, stretch)
        front = await self.witness.render(source, FRONT)
        gray = await self.witness.render(source, GRAY)
        sides = await self.witness.render(source, SIDES)
        detail = front_closeups(front)
        return Candidate(source, contact_sheet(detail, gray, sides), raw, lineage, detail, pitch, stretch, yaw)

    async def surgical(self, parent, feedback, *, ident=1600, outputs=44000, reserve=250000):
        """Spend one late rewrite on measured local repairs, preserving its parent."""
        # Protect enough credit for a complete edit request and two-order votes.
        content = self.target() + [
            {"type": "input_text", "text": "CURRENT REPLICA: enlarged four front views, then full comparison sheet."},
            {"type": "input_image", "image_url": png_url(parent.detail), "detail": "high"},
            {"type": "input_image", "image_url": png_url(parent.sheet), "detail": "high"},
            {"type": "input_text", "text": "Construction brief:\n" + self.brief + "\nEarlier observations:\n" + feedback},
        ]
        patch_content = list(content) + [
            {"type": "input_text", "text": "CURRENT RAW SOURCE:\n" + parent.raw},
        ]
        patch_reserve = charge(SOL, input_bound(prompts.SURGEON, patch_content, PATCH_SCHEMA) + 24000, outputs) + reserve
        diagnostic = None
        for model in (ASTRA, SOL):
            if self.budget.allows(model, input_bound(prompts.DIAGNOSE, content), 6000, patch_reserve):
                diagnostic = await self.call(ident, model, prompts.DIAGNOSE, content, 6000,
                                             reserve=patch_reserve, effort="medium")
                break
        if not diagnostic:
            return [(parent, feedback)]
        patch_content.append({"type": "input_text", "text": "LOCAL REPAIR SPECIFICATION:\n" + diagnostic})
        patch = await self.call(ident + 100, SOL, prompts.SURGEON, patch_content, outputs,
                                schema=PATCH_SCHEMA, reserve=reserve, effort="xhigh")
        if not patch:
            return [(parent, feedback)]
        try:
            raw = apply_edits(parent.raw, patch)
            if raw == parent.raw:
                return [(parent, feedback)]
            child = await self.render(raw, lineage=parent.lineage)
        except (ValueError, KeyError, TypeError, RenderRejected):
            # Ambiguous patches and invalid geometry cannot displace the parent.
            # Infrastructure errors still propagate to durable capture recovery.
            return [(parent, feedback)]
        return await self.rank([parent, child], ident + 200, compressed=True, reserve=100000)

    async def aligned(self, parent):
        """Shortlist free pixel probes; never let a silhouette alone pick output."""
        if alignment.foreground(self.image, reference=True) is None:
            return parent
        start_grid = await self.witness.render(parent.source, POSE_PROBE)
        initial = alignment.similarity(self.image, start_grid)
        if initial is None:
            return parent
        proposals = []
        for angle in (-90, -30, -15, 15, 30, 90):
            yaw = math.radians(angle)
            source = normalize(parent.raw, yaw, parent.pitch, parent.stretch)
            try:
                grid = await self.witness.render(source, POSE_PROBE)
            except (RenderRejected, ValueError):
                continue
            match = alignment.similarity(self.image, grid)
            if match is not None and match >= initial + .025:
                proposals.append((match, angle))
        proposals.sort(key=lambda row: (-row[0], abs(row[1]), row[1]))
        variants = [parent]
        for _, angle in proposals[:2]:
            try:
                candidate = await self.render(parent.raw, yaw=math.radians(angle), pitch=parent.pitch,
                                               stretch=parent.stretch, lineage=parent.lineage)
            except (RenderRejected, ValueError):
                continue
            if candidate.sheet != parent.sheet:
                variants.append(candidate)
        ranked = await self.rank(variants, 1900, compressed=True)
        return ranked[0][0]

    def construction(self, strategy, parent, feedback):
        content = self.target()
        text = "Construction brief:\n" + self.brief + "\nApproach: " + strategy
        if parent:
            text += (
                "\nImprove the following candidate, preserving its successful features. "
                "Return the complete module. Fix the largest visible errors before small details.\n"
                "Specific corrections:\n" + feedback + "\nCurrent module:\n" + parent.raw
            )
            content.append({"type": "input_image", "image_url": png_url(parent.sheet), "detail": "high"})
            if parent.detail:
                content.append({"type": "input_text", "text": "ENLARGED ORIGINAL FRONT VIEWS; inspect silhouette, ratios, thickness and material details."})
                content.append({"type": "input_image", "image_url": png_url(parent.detail), "detail": "high"})
        content.append({"type": "input_text", "text": text})
        return content

    async def finish(self, ident, raw, content, *, lineage, reserve):
        if raw is None:
            return None
        try:
            return await self.render(raw, lineage=lineage)
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
                return await self.render(repair, lineage=lineage)
            except (RenderRejected, ValueError):
                return None

    async def build(self, ident, *, model=SOL, strategy="", parent=None, feedback="", reserve=500000,
                    effort="high", outputs=24576):
        content = self.construction(strategy, parent, feedback)
        raw = await self.call(ident, model, prompts.BUILD, content, outputs, reserve=reserve, effort=effort)
        return await self.finish(ident, raw, content, lineage=parent.lineage if parent else ident, reserve=reserve)

    async def improve_stage(self, parents, ident, *, model=SOL, effort="high", outputs=24576,
                            reserve=0, strategy=""):
        """Reserve the whole parallel stage and settle in stable parent order."""
        requests = []
        reserved = 0
        for index, (parent, feedback) in enumerate(parents):
            content = self.construction(strategy, parent, feedback)
            upper = charge(model, input_bound(prompts.BUILD, content), outputs)
            if (self.budget.spent + reserved + upper + reserve > LIMIT - 100000
                    or self.budget.calls + len(requests) + 1 > 60):
                break
            params = dict(request_id=ident + index, model=model, instructions=prompts.BUILD,
                          input=[{"role": "user", "content": content}], store=False, service_tier="default",
                          reasoning={"effort": effort}, max_output_tokens=outputs)
            requests.append((params, parent))
            reserved += upper
        responses = await asyncio.gather(*(self.witness.responses.create(**r) for r, _ in requests),
                                         return_exceptions=True)
        for response in responses:
            if isinstance(response, BaseException):
                raise response
            self.budget.consume(model, response)
        children = []
        for (params, parent), response in zip(requests, responses):
            raw = response.output_text.strip() if response.status == "completed" and response.output_text else None
            child = await self.finish(params["request_id"], raw, list(params["input"][0]["content"]),
                                      lineage=parent.lineage, reserve=reserve)
            if child is not None:
                children.append(child)
        return children

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
                self.budget.spent + reserved + upper + 2500000 > LIMIT - 100000
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
                candidate = await self.render(raw, lineage=request["request_id"])
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
                    request["request_id"] + 10000, SOL, prompts.BUILD, content, 24576, reserve=2500000
                )
                if not repaired:
                    continue
                try:
                    candidate = await self.render(repaired, lineage=request["request_id"])
                except (RenderRejected, ValueError):
                    continue
            candidates.append(candidate)
        return candidates

    async def rank(self, candidates, ident, *, keep=1, mirror=True, reserve=0, distinct_lineages=False, compressed=False):
        # The first candidate is the incumbent and wins close/noisy comparisons.
        candidates = list({c.source: c for c in candidates if c is not None}.values())
        if not candidates:
            return []
        if len(candidates) == 1:
            return [(candidates[0], "")]
        indices = list(range(len(candidates)))
        indices.sort(key=lambda i: hashlib.sha256(f"{self.seed}:{self.identity}:{ident}:{i}".encode()).digest())
        scores = {i: [] for i in indices}
        notes = {i: [] for i in indices}
        for order_index in range(2 if mirror else 1):
            order = indices if order_index == 0 else list(reversed(indices))
            labels = {chr(65 + j): i for j, i in enumerate(order)}
            content = self.target(compressed=compressed)
            content.append({"type": "input_text", "text": "Construction brief:\n" + self.brief})
            for label, i in labels.items():
                content.extend(
                    [
                        {"type": "input_text", "text": "CANDIDATE " + label},
                        {"type": "input_image", "image_url": (jpeg_url if compressed else png_url)(candidates[i].sheet), "detail": "high"},
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
                reserve=reserve,
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
        if not counts or any(count != (2 if mirror else 1) for count in counts):
            fallback = []
            for candidate in candidates:
                if not distinct_lineages or all(candidate.lineage != c.lineage for c, _ in fallback):
                    fallback.append((candidate, ""))
                if len(fallback) == keep:
                    break
            return fallback
        means = {i: sum(scores[i]) / len(scores[i]) for i in indices}
        # Compare every challenger directly with the incumbent. A chain of small
        # pairwise tolerances must not accumulate into a position-sensitive win.
        eligible = [i for i in range(1, len(candidates))
                    if means[i] < means[0] - 0.18
                    and all(a <= b + 0.1 for a, b in zip(scores[i], scores[0]))]
        winner = min(eligible, key=lambda i: (means[i], i)) if eligible else 0
        order = [winner] + sorted((i for i in indices if i != winner), key=lambda i: (means[i], i))
        selected = []
        for i in order:
            if distinct_lineages and any(c.lineage == candidates[i].lineage for c, _ in selected):
                continue
            selected.append((candidates[i], "\n".join(notes[i])))
            if len(selected) == keep:
                break
        return selected

    async def select(self, candidates, ident, *, mirror=True):
        ranked = await self.rank(candidates, ident, mirror=mirror)
        return ranked[0] if ranked else (None, "")


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
    beam = await search.rank(candidates, 100, keep=3, distinct_lineages=True, reserve=2300000)
    if not beam:
        return None
    children = await search.improve_stage(
        beam, 200, reserve=2100000,
        strategy="PROPORTION PASS: re-measure overall width:height:depth and the three largest parts against the photo. "
                 "Correct silhouette, curvature, openings and thickness before adding small marks. Preserve actual part counts.")
    beam = await search.rank([c for c, _ in beam] + children, 300, keep=2,
                             distinct_lineages=True, reserve=1900000)
    children = await search.improve_stage(
        beam, 400, model=ASTRA, reserve=1350000,
        strategy="Sculpt the defining shape and identifying features. Use the enlarged front views to fix "
                 "the largest remaining geometric errors; preserve successful proportions and visible color regions.")
    beam = await search.rank([c for c, _ in beam] + children, 500, keep=2,
                             distinct_lineages=True, reserve=1100000)
    children = await search.improve_stage(
        beam, 600, effort="xhigh", outputs=44000, reserve=700000,
        strategy="HIGH QUALITY RECONSTRUCTION: carefully reason through all major ratios and curved contours, "
                 "then implement a complete improved model. Match the actual object rather than its generic category. "
                 "Preserve identity, material regions and real volume; avoid spending the budget on invisible tessellation.")
    beam = await search.rank([c for c, _ in beam] + children, 700, reserve=600000)
    # These are sequential improvements: each step receives the selected result
    # and critique from the preceding stage, rather than making sibling rewrites.
    for ident, selection in ((800, 900),):
        children = await search.improve_stage(
            beam, ident, effort="xhigh", outputs=44000, reserve=180000,
            strategy="FINAL LIKENESS PASS: fix the most consequential remaining mismatch shown in the photo "
                     "and enlarged previews. Check ratios, contour transitions, identifying part sizes and material tones. "
                     "Keep established correct geometry and leave safe validation headroom.")
        beam = await search.rank([c for c, _ in beam] + children, selection, reserve=100000)
    beam = await search.surgical(*beam[0])
    # Re-inspect the selected repair, then address its remaining visible defect.
    # Keep ample final comparison headroom; the entire pass is skipped when its
    # diagnostic, complete edit response and comparison cannot fit together.
    beam = await search.surgical(*beam[0], ident=2100, outputs=32768, reserve=500000)
    winner = beam[0][0]
    # Bounded numeric proportion search is evaluated on complete 3D assets.
    # Keep the untouched parent whenever a distortion is worse or ambiguous.
    variants = [winner]
    for stretch in ((.88, 1, 1), (1.12, 1, 1), (1, .88, 1), (1, 1.12, 1)):
        try:
            candidate = await search.render(winner.raw, lineage=winner.lineage, stretch=stretch)
        except (RenderRejected, ValueError):
            continue
        if candidate.sheet != winner.sheet:
            variants.append(candidate)
    winner, _ = (await search.rank(variants, 1300, compressed=True, reserve=200000))[0]
    variants = [winner]
    for pitch in (-math.pi / 12, math.pi / 12):
        try:
            candidate = await search.render(winner.raw, pitch=pitch, lineage=winner.lineage, stretch=winner.stretch)
        except (RenderRejected, ValueError):
            continue
        if candidate.sheet != winner.sheet:
            variants.append(candidate)
    winner, _ = (await search.rank(variants, 1400, compressed=True))[0]
    # This is exactly the source that was rendered, not a post-selection rewrite.
    winner = await search.aligned(winner)
    return winner.source
