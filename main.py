"""Root competition entry point and official witness batch launcher."""

import asyncio
from miner404.pipeline import run as run_pipeline
from miner404.versions import ACTIVE_PLAN


class WitnessBridge:
    """Use only the runtime supplied witness; never access credentials in generation."""
    def __init__(self, witness, loop):
        self.witness, self.loop = witness, loop

    def create(self, **params):
        return asyncio.run_coroutine_threadsafe(self.witness.responses.create(**params), self.loop).result()

    def render(self, source, options):
        return asyncio.run_coroutine_threadsafe(self.witness.render(source, options), self.loop).result()


async def generate(image: bytes, seed: int, witness) -> str | None:
    bridge = WitnessBridge(witness, asyncio.get_running_loop())
    return await asyncio.to_thread(run_pipeline, image, seed, bridge, bridge, ACTIVE_PLAN)

__all__ = ["generate"]


async def main():
    import argparse
    from pathlib import Path

    from miner_runtime.batch import run

    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--prompts", type=Path)
    inputs.add_argument("--image", action="append")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--wallet-name", default="miner")
    parser.add_argument("--wallet-hotkey", default="default")
    parser.add_argument("--wallet-path", default="~/.bittensor/wallets")
    parser.add_argument("--workers", "--parallel-prompts", dest="workers", type=int, default=24)
    parser.add_argument("--parallel-calls", type=int, default=32)
    parser.add_argument("--parallel-preparations", type=int, default=4)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args()
    sources = [s.strip() for s in args.prompts.read_text().splitlines() if s.strip()] if args.prompts else args.image
    mapped = {Path(source).stem: source for source in sources}
    if len(mapped) != len(sources):
        parser.error("Duplicate image stems: preserve the official unique prompt filenames")
    await run(
        generate,
        mapped,
        args.seed,
        witness_config=Path(__file__).with_name("witness.json"),
        workers=args.workers,
        parallel_calls=args.parallel_calls,
        parallel_preparations=args.parallel_preparations,
        attempts=args.attempts,
        wallet_name=args.wallet_name,
        wallet_hotkey=args.wallet_hotkey,
        wallet_path=args.wallet_path,
        api=args.api,
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
