"""Development only: OpenRouter experiments, local renders and exact cached replay.

Never imported by the competition entry point. Credentials remain outside source.
These logs are not official witness evidence and cannot be submitted as such.
"""

import argparse
import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI
from PIL import Image
from renderer_client import RenderRejected

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DevelopmentWitness:
    def __init__(self, directory, key_file=None, renderer="http://127.0.0.1:18040", offline=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.renderer = renderer
        self.responses = self
        self.trace = []
        self.actual_cost = 0.0
        self.client = (
            None
            if offline
            else AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=Path(key_file).read_text().strip(),
                timeout=900,
                max_retries=0,
            )
        )

    def path(self, kind, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(body.encode()).hexdigest()
        self.trace.append({"kind": kind, "sha256": digest})
        return self.directory / (kind + "-" + digest)

    async def create(self, **params):
        path = self.path("call", params).with_suffix(".json")
        if path.exists():
            saved = json.loads(path.read_text())
        else:
            if self.offline:
                raise RuntimeError("Replay request mismatch: " + path.name)
            messages = [{"role": "system", "content": params["instructions"]}]
            for message in params["input"]:
                content = []
                for item in message["content"]:
                    content.append(
                        {"type": "text", "text": item["text"]}
                        if item["type"] == "input_text"
                        else {
                            "type": "image_url",
                            "image_url": {"url": item["image_url"], "detail": item.get("detail", "high")},
                        }
                    )
                messages.append({"role": message["role"], "content": content})
            request = {
                "model": "openai/" + params["model"],
                "messages": messages,
                "max_tokens": params["max_output_tokens"],
                "extra_body": {"reasoning": params["reasoning"]},
            }
            if "text" in params:
                fmt = params["text"]["format"]
                request["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": fmt["name"], "strict": True, "schema": fmt["schema"]},
                }
            print("CALL", params["request_id"], params["model"], flush=True)
            result = await self.client.chat.completions.create(**request)
            usage = result.usage
            saved = {
                "request_id": params["request_id"],
                "model": params["model"],
                "status": "completed" if result.choices[0].finish_reason == "stop" else "incomplete",
                "output_text": result.choices[0].message.content or "",
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
                "usage": usage.model_dump(),
                "request": params,
            }
            path.write_text(json.dumps(saved))
        cost = saved["usage"].get("cost", 0) or 0
        self.actual_cost += cost
        print(
            "DONE",
            saved["request_id"],
            saved["status"],
            saved["input_tokens"],
            saved["output_tokens"],
            "bill=$" + str(round(cost, 5)),
            flush=True,
        )
        return SimpleNamespace(
            status=saved["status"],
            output_text=saved["output_text"],
            usage=SimpleNamespace(input_tokens=saved["input_tokens"], output_tokens=saved["output_tokens"]),
        )

    async def render(self, source, options):
        path = self.path("render", {"source": source, "options": options.query()})
        rejection = path.with_suffix(".rejection.json")
        png = path.with_suffix(".png")
        if rejection.exists():
            raise RenderRejected(rejection.read_text())
        if png.exists():
            return png.read_bytes()
        if self.offline:
            raise RuntimeError("Replay render mismatch: " + path.name)
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(self.renderer + "/render/grid", params=options.query(), json={"source": source})
        if r.status_code == 422:
            rejection.write_text(r.text)
            print("REJECTED", r.text[:900], flush=True)
            raise RenderRejected(r.text)
        r.raise_for_status()
        if not r.content.startswith(b"\x89PNG"):
            raise ValueError("Expected a PNG render")
        png.write_bytes(r.content)
        return r.content

    async def close(self):
        if self.client:
            await self.client.close()


async def run(args):
    from miner.pipeline import FRONT, GRAY, SIDES, contact_sheet, generate

    image = Path(args.image).read_bytes()
    witness = DevelopmentWitness(args.output, args.key_file, args.renderer, args.replay)
    try:
        source = await generate(image, args.seed, witness)
        output = Path(args.output)
        if args.replay:
            expected = (output / "selected.js").read_text() if (output / "selected.js").exists() else None
            trace = json.loads((output / "trace.json").read_text())
            if source != expected or trace != witness.trace:
                raise RuntimeError("Replay differs in output or call/render order")
            print("EXACT_REPLAY_PASSED", len(witness.trace), "observations", flush=True)
        else:
            if source:
                (output / "selected.js").write_text(source)
            (output / "trace.json").write_text(json.dumps(witness.trace, indent=2))
            (output / "result.json").write_text(
                json.dumps(
                    {
                        "success": source is not None,
                        "source_sha256": hashlib.sha256(source.encode()).hexdigest() if source else None,
                        "openrouter_reported_cost_usd": witness.actual_cost,
                        "image_sha256": hashlib.sha256(image).hexdigest(),
                        "seed": args.seed,
                        "official_witness": False,
                    },
                    indent=2,
                )
            )
            if source:
                # Use cached previews: do not add these artifact writes to the trace.
                original_trace = list(witness.trace)
                views = [await witness.render(source, option) for option in (FRONT, GRAY, SIDES)]
                witness.trace[:] = original_trace
                (output / "selected.png").write_bytes(contact_sheet(*views))
                with Image.open(io.BytesIO(image)) as im:
                    im.thumbnail((768, 768))
                    im.convert("RGB").save(output / "reference.png")
            print("RESULT", source is not None, "bill=$", round(witness.actual_cost, 4), flush=True)
    finally:
        await witness.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--key-file", default="/root/404-gen-key.txt")
    parser.add_argument("--renderer", default="http://127.0.0.1:18040")
    parser.add_argument("--replay", action="store_true")
    asyncio.run(run(parser.parse_args()))
