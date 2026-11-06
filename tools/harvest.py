"""Export completed development drafts without buying inference or inventing results."""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from renderer_client import RenderRejected

from miner.pipeline import FRONT, GRAY, SIDES, contact_sheet, normalize
from tools.develop import DevelopmentWitness


async def main(args):
    records = []
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for directory in sorted(Path(args.experiments).iterdir()):
        if not directory.is_dir():
            continue
        witness = DevelopmentWitness(directory, offline=True)
        for path in sorted(directory.glob("call-*.json")):
            response = json.loads(path.read_text())
            ident = response["request_id"]
            if not 10 <= ident <= 15 or response["status"] != "completed":
                continue
            name = directory.name + "-draft" + str(ident)
            record = {"name": name, "status": "draft_not_final_pipeline_selection"}
            try:
                code = normalize(response["output_text"])
                views = [await witness.render(code, option) for option in (FRONT, GRAY, SIDES)]
                source = output / (name + ".js")
                source.write_text(code)
                (output / (name + ".png")).write_bytes(contact_sheet(*views))
                checked = await asyncio.to_thread(
                    subprocess.run,
                    [args.node, args.validator, "--json", str(source)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                validation = json.loads(checked.stdout)
                record.update(
                    passed=validation["passed"],
                    metrics=validation["metrics"],
                    failures=validation["failures"],
                    total_ms=validation["totalMs"],
                )
            except (RuntimeError, ValueError, TypeError, KeyError, OSError, RenderRejected) as error:
                record.update(passed=False, error=str(error))
            records.append(record)
    (output / "validation.json").write_text(json.dumps(records, indent=2))
    print(json.dumps({"drafts": len(records), "passed": sum(r.get("passed", False) for r in records)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiments", default="experiments")
    parser.add_argument("--output", default="/root/404-round3-results")
    parser.add_argument("--node", default="/root/404-dev-venv/bin/node")
    parser.add_argument("--validator", default="/root/404-gen-subnet/miner-reference/tools/validate.js")
    asyncio.run(main(parser.parse_args()))
