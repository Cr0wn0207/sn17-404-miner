# Round 4 candidate: deep candidate refinement

`main.generate(image, seed, witness)` creates a procedural Three.js module from one image.
This source is prepared for the Round 4 competition. Local proxy judging is
diagnostic and does not establish an official competition score.

The generator makes six Sol drafts, selects one lineage using mirrored render comparisons,
and applies up to ten gated Sol/Astra refinement steps. Budget admission can skip steps.
Pose, bounding-box fit and metallic material adjustments remain enabled. The final transformed
module is rendered again; a rejected transformation falls back to a previously valid parent.

Actual output token limits are 24,000 for ordinary Sol generation, 36,000 for Sol xhigh,
18,500 for Astra and 2,048 for selection. Reservations use those full requested limits,
with 6% credit headroom. Actual usage is still charged for every captured usable response.
Input token estimates remain estimates; independent runtime accounting is authoritative.
Per-prompt competition limits remain 60 calls and 5,000,000 credits.

The deep single-lineage plan is adopted from `taohunter251/lark-ridge` at registered commit
`20a6f55765f06137c3c589b3c28f77b152da11e1`, on the reviewed heron-quay engine baseline.
See `UPSTREAM_SOURCES.txt`, `LICENSE` and `UPSTREAM_LICENSE` for provenance.
The upstream observed result is not a measurement or guarantee for V30.

The local `witness.json` selects the existing Codex subscription credentials by configuration.
Never publish credentials, witness caches, generated outputs or private experimental sessions.

## Validation

```bash
python -m pytest tests/test_dual_lineage.py tests/test_deep_lineage.py
```

The separate local benchmark runs generation, actual resource checks, exact cached replay,
and blinded two-order Sol/Astra S1/S4 proxy comparisons. It preserves renderer errors as
ordered observations so transient service failures do not disappear during replay.
Those records are development diagnostics, not formal Witness proofs or official GLM scores.

The CLI uses miner-runtime 0.1.6, witness-client 0.2.18 and the Round 4 concurrency
settings (`--workers 24 --parallel-calls 32 --parallel-preparations 4`) by default.
Round 3's original registration and generated outputs remain frozen. The registered
Round 4 commit must be fixed before its prompts and seed are published.
