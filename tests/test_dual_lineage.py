"""Exercise the active entry point, concurrent accounting and lineage decisions."""
import asyncio
import collections
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from main import generate
from miner404 import orient
from miner404.budget import Budget
from miner404.images import zoomed_views
from miner404.pipeline import Candidate, Judgement, Pipeline, Step


def picture(grid=False):
    image = Image.new('RGB', (256, 256), 'white')
    draw = ImageDraw.Draw(image)
    for x, y in ([(0, 0), (128, 0), (0, 128), (128, 128)] if grid else [(64, 64)]):
        draw.rectangle((x + 32, y + 24, x + 96, y + 100), fill=(180, 60, 30))
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


SOURCE = '''export default function generate(THREE) {
const root = new THREE.Group();
root.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
new THREE.MeshStandardMaterial({color: 0xb43c1e})));
return root;
}'''


class RecordingWitness:
    def __init__(self, fail=False):
        self.responses = self
        self.calls, self.renders = [], []
        self.fail = fail

    async def create(self, **params):
        self.calls.append(params)
        if self.fail:
            raise ConnectionError('test transport failure')
        if 'text' in params:
            schema = params['text']['format']['schema']
            labels = schema['properties']['candidates']['items']['properties']['label']['enum']
            rows = [dict(label=label, front_left=2, front_right=2, front_below=2,
                         front_above=2, grid=2, garbage_sides=0, fixes=[]) for label in labels]
            text = json.dumps({'candidates': rows})
        else:
            text = SOURCE + '\n// request ' + str(params['request_id'])
        return SimpleNamespace(status='completed', output_text=text,
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=500))

    async def render(self, source, options):
        self.renders.append((source, options.query()))
        return picture(grid=True)


def test_entry_point_replays_same_requests_renders_and_output(monkeypatch):
    monkeypatch.setattr(orient, 'best_yaw', lambda *args: None)
    monkeypatch.setattr(orient, 'is_flat', lambda *args: False)
    first, replay = RecordingWitness(), RecordingWitness()
    out = asyncio.run(generate(picture(), 1234, first))
    repeated = asyncio.run(generate(picture(), 1234, replay))
    assert out == repeated and 'export default' in out
    canonical = lambda calls: sorted((json.dumps(c, sort_keys=True) for c in calls))
    assert canonical(first.calls) == canonical(replay.calls)
    assert first.renders == replay.renders
    ids = [call['request_id'] for call in first.calls]
    assert len(ids) == len(set(ids)) <= 60
    authored = [i for i in ids if 1 <= i <= 6 or 100 <= i < 700]
    assert len(authored) == 18, 'Six drafts and twelve lineage rewrites must actually execute'
    assert all(call['service_tier'] == 'default' for call in first.calls)
    assert all(options['lighting'] == 'neutral' for _, options in first.renders)


def candidate(name):
    return Candidate(name, SOURCE, picture(True), picture(True), SOURCE, zoomed_views(picture(True)))


@pytest.mark.parametrize('gap,replace_parent', [(0.24, True), (0.25, True), (0.26, False)])
def test_lineage_update_preserves_ownership_and_margin(gap, replace_parent):
    pipeline = Pipeline(picture(), 3, None, None)
    parents, children = [candidate('p0'), candidate('p1')], [candidate('c0'), candidate('c1')]
    pipeline.modules = lambda *args: children
    pipeline.scores = lambda *args: {
        'p0': Judgement(2, []), 'c0': Judgement(2 + gap, []),
        'p1': Judgement(1, []), 'c1': Judgement(4, [])}
    with ThreadPoolExecutor() as pool:
        result = pipeline.advance(pool, parents, Step(rewrites=(('gpt-6.1-sol', 'high'),), each_lineage=True), 0)
    assert result[0] is (children[0] if replace_parent else parents[0])
    assert result[1] is parents[1], 'A winning child in another lineage must not eliminate this lineage'
    assert children[0].parent is parents[0] and children[1].parent is parents[1]


def test_missing_verdict_preserves_both_parents():
    pipeline = Pipeline(picture(), 3, None, None)
    parents = [candidate('p0'), candidate('p1')]
    pipeline.modules = lambda *args: [candidate('c0'), candidate('c1')]
    pipeline.scores = lambda *args: {}
    with ThreadPoolExecutor() as pool:
        assert pipeline.advance(pool, parents, Step(rewrites=(('gpt-6.1-sol', 'high'),), each_lineage=True), 0) == parents


def test_parallel_reservations_cannot_overbook():
    budget = Budget()
    barrier = threading.Barrier(8)
    def reserve(_):
        barrier.wait()
        return budget.reserve(1_000_000)
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(reserve, range(8)))
    assert sum(accepted) == 4
    for _ in range(4):
        budget.settle(1_000_000, 'gpt-6.1-sol', SimpleNamespace(input_tokens=0, output_tokens=100_000))
    assert budget.calls == 4 and budget.credits == 4_000_000
    assert not budget.reserve(900_000)


def test_usage_charges_all_input_including_cached_and_reasoning():
    budget = Budget()
    assert budget.reserve(250_000)
    usage = SimpleNamespace(input_tokens=10_000, output_tokens=20_000,
                            input_tokens_details=SimpleNamespace(cached_tokens=9999))
    budget.settle(250_000, 'gpt-6.1-sol', usage)
    assert budget.credits == 220_000 and budget.calls == 1


def test_cropped_views_are_byte_deterministic_and_bounded():
    first = zoomed_views(picture(True))
    assert first == zoomed_views(picture(True)) and len(first) == 4
    assert all(512 <= Image.open(io.BytesIO(view)).width <= 768 for view in first)
