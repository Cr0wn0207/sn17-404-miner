"""How closely a view matches the photo, as one number: the cosine of two image embeddings. NumPy and Pillow only.

The embedding is a small vision transformer (ViT-S/16, 12 blocks, 384 wide) evaluated in integer arithmetic, so every
machine computes the same bits and a replay reproduces every choice made from it:

* each matrix product has integer-valued float64 operands whose partial sums stay far below 2**53, so BLAS returns
  the exact integer whatever its kernel, thread count or summation order (`_mm` checks the bound);
* the rest is int64 arithmetic, table lookups and one IEEE square root per normalisation, which is correctly rounded;
* images are resized by Pillow's fixed-point bilinear filter and never touched in floating point.

`similarity` is an integer in millionths. Nothing here reads the clock, the network or the file system beyond the
committed table file next to this module.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image

A = 12  # fraction bits of activations
WB = 13  # fraction bits of weights
ONE = 1 << A
SIDE = 224
GRID = SIDE // 16
PREFIX = 5  # class token and four register tokens: not rotated by the position code
LIMIT = float(1 << 52)

_TABLES: dict[str, np.ndarray] | None = None


def tables() -> dict[str, np.ndarray]:
    global _TABLES
    if _TABLES is None:
        with np.load(Path(__file__).with_name("dino_tables.npz")) as stored:
            _TABLES = {name: stored[name].astype(np.int64) for name in stored.files}
        for name in list(_TABLES):  # float copies of the matrices, made once: BLAS wants float64
            if name.endswith("_m"):
                _TABLES[name + "f"] = _TABLES[name].astype(np.float64)
    return _TABLES


def _mm(x: np.ndarray, w: np.ndarray, shift: int) -> np.ndarray:
    """Exact integer matrix product through float64 BLAS, then an arithmetic shift."""
    xf = x.astype(np.float64)
    if float(np.abs(xf).max()) * float(np.abs(w).max()) * x.shape[-1] >= LIMIT:
        raise OverflowError("matrix product would leave the exact float64 range")
    return (xf @ w).astype(np.int64) >> shift


def _norm(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = x.shape[-1]
    d = x - x.sum(-1, keepdims=True) // n
    var = (d * d).sum(-1, keepdims=True) // n + 168  # 1e-5 at 2A fraction bits
    std = np.maximum(np.floor(np.sqrt(var.astype(np.float64))).astype(np.int64), 1)
    return (((d << A) // std) * w >> A) + b


def _gelu(u: np.ndarray, table: np.ndarray) -> np.ndarray:
    step = ONE // 256
    c = np.clip(u, -8 * ONE, 8 * ONE) + 8 * ONE
    i = c // step
    f = c - i * step
    j = np.minimum(i + 1, len(table) - 1)
    y = table[i] + ((table[j] - table[i]) * f) // step
    return np.where(u > 8 * ONE, u, np.where(u < -8 * ONE, 0, y))


def _softmax(a: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Logits with A fraction bits to probabilities with 15 fraction bits."""
    step = ONE // 64
    t = np.minimum(a.max(-1, keepdims=True) - a, 16 * ONE - 1)
    i = t // step
    e = table[i] + ((table[i + 1] - table[i]) * (t - i * step)) // step
    return (e << 15) // e.sum(-1, keepdims=True)


def embed_many(images: np.ndarray) -> np.ndarray:
    """The embeddings (n x 384 int64) of n SIDE x SIDE RGB uint8 images, each exactly as if embedded alone."""
    t = tables()
    count = images.shape[0]
    x = ((images.astype(np.int64) * 1000 - t["mean"]) << A) // t["std"]
    patches = x.transpose(0, 3, 1, 2).reshape(count, 3, GRID, 16, GRID, 16).transpose(0, 2, 4, 1, 3, 5).reshape(count, GRID * GRID, 768)
    tokens = np.concatenate([np.broadcast_to(t["cls"], (count, 1, 384)), np.broadcast_to(t["reg"], (count, 4, 384)),
                             _mm(patches, t["patch_mf"], WB) + t["patch_b"]], 1)
    cos, sin = t["cos"], t["sin"]

    def rotated(a: np.ndarray) -> np.ndarray:  # a: images x heads x tokens x 64
        p = a[:, :, PREFIX:]
        turn = (p * cos + np.concatenate([-p[..., 32:], p[..., :32]], -1) * sin) >> 14
        return np.concatenate([a[:, :, :PREFIX], turn], 2)

    for layer in range(12):
        h = _norm(tokens, t[f"{layer}_n1w"], t[f"{layer}_n1b"])
        qkv = _mm(h, t[f"{layer}_qkv_mf"], WB).reshape(count, -1, 3, 6, 64).transpose(2, 0, 3, 1, 4)
        q, k, v = rotated(qkv[0]), rotated(qkv[1]), qkv[2]
        qf, kf = q.astype(np.float64), k.astype(np.float64)
        if float(np.abs(qf).max()) * float(np.abs(kf).max()) * 64 >= LIMIT:
            raise OverflowError("attention product would leave the exact float64 range")
        logits = (qf @ kf.transpose(0, 1, 3, 2)).astype(np.int64) >> (A + 3)
        vf = v.astype(np.float64)
        if float(np.abs(vf).max()) * 32768.0 * vf.shape[-2] >= LIMIT:
            raise OverflowError("attention mix would leave the exact float64 range")
        mixed = (_softmax(logits, t["exp"]).astype(np.float64) @ vf).astype(np.int64) >> 15
        out = _mm(mixed.transpose(0, 2, 1, 3).reshape(count, -1, 384), t[f"{layer}_o_mf"], WB) + t[f"{layer}_ob"]
        tokens = tokens + (out * t[f"{layer}_ls1"] >> 16)
        h = _norm(tokens, t[f"{layer}_n2w"], t[f"{layer}_n2b"])
        u = _gelu(_mm(h, t[f"{layer}_up_mf"], WB) + t[f"{layer}_upb"], t["gelu"])
        tokens = tokens + ((_mm(u, t[f"{layer}_down_mf"], WB) + t[f"{layer}_downb"]) * t[f"{layer}_ls2"] >> 16)
    return _norm(tokens[:, :1], t["norm_w"], t["norm_b"])[:, 0]


def embed(pixels: np.ndarray) -> np.ndarray:
    """The embedding (384 int64 values) of a SIDE x SIDE RGB uint8 image."""
    return embed_many(pixels[None])[0]


def similarity(a: np.ndarray, b: np.ndarray) -> int:
    """Cosine of two embeddings in millionths, rounded down. Exact: Python integers."""
    x, y = [int(v) for v in a], [int(v) for v in b]
    scale = math.isqrt(sum(v * v for v in x) * sum(v * v for v in y))
    return sum(p * q for p, q in zip(x, y, strict=True)) * 1_000_000 // scale if scale else 0


def _pixels(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB").resize((SIDE, SIDE), Image.Resampling.BILINEAR))


def photo_embedding(image: bytes) -> np.ndarray:
    return embed(_pixels(Image.open(io.BytesIO(image))))


def view_embeddings(grid: bytes, columns: int = 2, rows: int = 2) -> list[np.ndarray]:
    """One embedding per tile of a gap-free render grid."""
    image = Image.open(io.BytesIO(grid)).convert("RGB")
    width, height = image.width // columns, image.height // rows
    tiles = [_pixels(image.crop((column * width, row * height, (column + 1) * width, (row + 1) * height)))
             for row in range(rows) for column in range(columns)]
    return list(embed_many(np.stack(tiles)))


def grid_similarity(grid: bytes, photo: np.ndarray) -> int:
    """Mean similarity of the four judge views to the photo, in millionths, rounded down."""
    values = [similarity(view, photo) for view in view_embeddings(grid)]
    return sum(values) // len(values)
