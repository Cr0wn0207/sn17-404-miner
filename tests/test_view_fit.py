"""The embedding is exact integer arithmetic, and the final view fit keeps a turn or tone only for a clear gain."""

import io

import numpy as np
from PIL import Image

from miner404 import dino, orient
from miner404.pipeline import GRADE_CALL, Pipeline, VIEW_FIT_GAIN, VIEW_GATE, VIEW_PICK_GAIN

WRAPPED = "function __asset404(THREE) { return new THREE.Group(); }\nroot.add(__asset404(THREE));\n" + GRADE_CALL + "\n"


def picture(seed: int, side: int = 96) -> Image.Image:
    rng = np.random.Generator(np.random.PCG64(seed))
    return Image.fromarray(rng.integers(0, 256, (side, side, 3), dtype=np.uint8), "RGB")


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_embedding_is_integer_and_repeatable():
    pixels = np.asarray(picture(1).resize((dino.SIDE, dino.SIDE)))
    first, second = dino.embed(pixels), dino.embed(pixels.copy())
    assert first.dtype == np.int64 and first.shape == (384,)
    assert (first == second).all()
    assert dino.similarity(first, first) in (999_999, 1_000_000)
    other = dino.embed(np.asarray(picture(2).resize((dino.SIDE, dino.SIDE))))
    assert dino.similarity(first, other) == dino.similarity(other, first) < 1_000_000


def test_matrix_products_are_exact_integers():
    """Float64 BLAS returns the same integers as Python's exact arithmetic for operands of the sizes used."""
    rng = np.random.Generator(np.random.PCG64(3))
    x = rng.integers(-(1 << 20), 1 << 20, (7, 384)).astype(np.int64)
    w = rng.integers(-(1 << 15), 1 << 15, (384, 96)).astype(np.int64)
    exact = (x.astype(object) @ w.astype(object))
    assert (dino._mm(x, w.astype(np.float64), 0).astype(object) == exact).all()


def test_reposed_wraps_any_pose_stage_call():
    plain = orient.reposed(WRAPPED, 15, -10, 0)
    assert "__fit404.add(__asset404(THREE)); root.add(__fit404);" in plain and "15 * Math.PI / 180" in plain
    turned = orient.reposed(orient.rotated(WRAPPED, 90), 0, 10, 0)
    assert "__fit404.add(__yaw404); root.add(__fit404);" in turned
    assert orient.reposed(WRAPPED, 0, 0, 0) == WRAPPED
    assert orient.reposed("no wrapper here", 15, 0, 0) == "no wrapper here"


class ScriptedRenderer:
    """Returns a picture chosen by markers in the source, so the search has a known best answer."""

    def __init__(self, target: Image.Image, other: Image.Image) -> None:
        self.target, self.other, self.calls = target, other, 0

    def render(self, source: str, options) -> bytes:
        self.calls += 1
        good = "rotation.set(0 * Math.PI / 180, -15 * Math.PI / 180, 0 * Math.PI / 180)" in source
        tile = self.target if good else self.other
        grid = Image.new("RGB", (2 * tile.width, 2 * tile.height))
        for row in range(2):
            for column in range(2):
                grid.paste(tile, (column * tile.width, row * tile.height))
        return png(grid)


def test_view_fit_keeps_only_a_clear_gain():
    target, other = picture(5), picture(6)
    renderer = ScriptedRenderer(target, other)
    pipeline = Pipeline(png(target), 0, None, renderer)
    fitted = pipeline.view_fitted(WRAPPED)
    assert "rotation.set(0 * Math.PI / 180, -15 * Math.PI / 180, 0 * Math.PI / 180)" in fitted
    assert GRADE_CALL in fitted  # no tone change gained anything
    same = ScriptedRenderer(other, other)
    assert Pipeline(png(target), 0, None, same).view_fitted(WRAPPED) == WRAPPED
    assert VIEW_FIT_GAIN > 0


def test_view_pick_returns_the_closest_module_of_the_winners_lineage():
    from miner404.pipeline import Candidate

    pipeline = Pipeline(png(picture(5)), 0, None, ScriptedRenderer(picture(5), picture(6)))

    def module(name: str, similarity: int, parent=None) -> Candidate:
        candidate = Candidate(name, name, b"", b"")
        candidate.similarity, candidate.parent = similarity, parent
        pipeline.visited.append(candidate)
        return candidate

    other_draft = module("d1", 990_000)  # another lineage: never picked, however close
    draft = module("d0", 700_000)
    early = module("r0", 760_000, draft)
    dropped = module("r1", 790_000, early)  # a rewrite the selector dropped still belongs to the lineage
    late = module("r2", 750_000, early)
    assert pipeline.view_picked(late) is dropped
    assert pipeline.view_picked(dropped) is dropped
    near = module("r3", 790_000 + VIEW_PICK_GAIN - 1, dropped)
    assert pipeline.view_picked(dropped) is dropped  # a lead under the margin does not move the pick
    assert pipeline.view_picked(near) is near
    assert other_draft.similarity > dropped.similarity


def test_closer_keeps_a_finishing_step_only_when_the_views_do_not_move_away():
    target, other = picture(5), picture(6)
    pipeline = Pipeline(png(target), 0, None, ScriptedRenderer(target, other))
    good = orient.reposed(WRAPPED, -15, 0, 0)
    assert pipeline.closer(WRAPPED, good) == good
    assert pipeline.closer(good, WRAPPED) == good
    assert pipeline.closer(WRAPPED, WRAPPED) == WRAPPED


def test_active_plan_finishes_by_view_similarity_without_the_forward_move():
    from miner404.versions import ACTIVE_PLAN

    assert ACTIVE_PLAN.view_fit and ACTIVE_PLAN.view_pick and not ACTIVE_PLAN.forward


def test_gate_overrules_the_vote_only_for_a_clear_move_of_the_views():
    from miner404.pipeline import Candidate

    pipeline = Pipeline(png(picture(5)), 0, None, ScriptedRenderer(picture(5), picture(6)))

    def module(similarity: int) -> Candidate:
        candidate = Candidate("m", "m", b"", b"")
        candidate.similarity = similarity
        return candidate

    parent = module(800_000)
    assert pipeline.gated(0, parent, module(700_000), True)  # view_gate off: the vote stands
    pipeline.view_gate = True
    assert pipeline.gated(0, parent, module(800_000 - VIEW_GATE + 1), True)
    assert not pipeline.gated(0, parent, module(800_000 - VIEW_GATE), True)
    assert not pipeline.gated(0, parent, module(800_000 + VIEW_GATE - 1), False)
    assert pipeline.gated(0, parent, module(800_000 + VIEW_GATE), False)
    assert pipeline.gated(0, parent, module(-1), True) and not pipeline.gated(0, parent, module(-1), False)
    assert ACTIVE_VIEW_GATE()


def ACTIVE_VIEW_GATE() -> bool:
    from miner404.versions import ACTIVE_PLAN

    return ACTIVE_PLAN.view_gate
