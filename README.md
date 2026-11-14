# Image to Three.js miner

Generates a Three.js module for a prompt image through the competition witness: drafts, selection, rewrites against
renders and a final pick, within the per-prompt budget.

Entry point: `main.py` -> `async generate(image, seed, witness) -> str | None`. The plan is in `miner404/versions.py`.

## What this version adds

Built on `TiltGilt/VertexLoom@2385ec1` (the Round 4 winner). Three steps use how closely the judge's four front
views match the photo, as the cosine of two DINOv3 ViT-S/16 embeddings computed in exact integer arithmetic
(`miner404/dino.py`, weights in `miner404/dino_tables.npz`, licence in `miner404/DINOV3_LICENSE.md`). No extra model
calls; a replay reproduces every choice bit for bit.

- `view_gate`: a round's two-call vote on a rewrite still decides, unless the views moved by 0.02 or more: a kept
  rewrite that moved clearly away from the photo is dropped, a dropped one that moved clearly closer is kept.
- `view_pick`: the chain finishes from the module of the winner's own lineage that is closest to the photo, when it
  leads the selector's last pick by 0.010.
- `view_check`: outline fit, photo tilt, stronger metal and the judged tilt are kept only when the views do not move
  away from the photo.

The final turn-and-tone fit (`view_fit`) is in the code but off: on 32 development prompts the judge preferred the
module without it.

## Live run

```sh
uv venv --python 3.13 .venv-live
uv pip install --python .venv-live/bin/python -r requirements.txt
git clone --branch miner-runtime-v0.1.5 --depth 1 https://github.com/404-Repo/404-gen-subnet.git ../404-sdk
```

Create `witness.json` next to `main.py`, with `witness_url` set to `https://witness.subnet404.xyz` and
`proof_parameters` set to the absolute path of `404-sdk/witness-server/verifier/params`. Then:

```sh
.venv-live/bin/python main.py --prompts prompts.txt --seed PUBLISHED_SEED --wallet-name NAME --wallet-hotkey HOTKEY
```
