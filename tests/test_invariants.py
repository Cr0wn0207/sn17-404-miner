import asyncio
import io
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image
from renderer_client import RenderRejected

from miner.budget import Budget, charge
from miner.pipeline import Candidate, Search, front_closeups, generate, normalize, parse_scores


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (40, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


SOURCE = """export default function generate(THREE) {
 const root = new THREE.Group();
 root.add(new THREE.Mesh(new THREE.BoxGeometry(2,1,3),new THREE.MeshStandardMaterial({color:0xcc6644})));
 return root;
}
"""


class FakeWitness:
    def __init__(self, reject=False, invalid=False, error=None, tied=False):
        self.responses = self
        self.reject = reject
        self.invalid = invalid
        self.error = error
        self.tied = tied
        self.trace = []

    async def create(self, **request):
        self.trace.append(("call", request))
        if self.error:
            raise self.error
        if request["request_id"] == 1:
            text = "Seven distinctive features and dimensions."
        elif "text" in request:
            labels = request["text"]["format"]["schema"]["properties"]["scores"]["items"]["properties"]["label"]["enum"]
            text = json.dumps(
                {
                    "scores": [
                        {
                            "label": label,
                            "front": [2, 2, 2, 2],
                            "feature_hits": 5,
                            "artifact": 1,
                            "bad_sides": 0,
                            "fixes": "Improve curves",
                        }
                        for label in labels
                    ]
                }
            )
        else:
            text = "bad source" if self.invalid else SOURCE + "\n// draft " + str(request["request_id"])
        return SimpleNamespace(
            status="completed", output_text=text, usage=SimpleNamespace(input_tokens=1000, output_tokens=500)
        )

    async def render(self, source, options):
        self.trace.append(("render", source, options))
        if self.reject:
            self.reject = False
            raise RenderRejected('{"error":"post_validation_failed","failures":[]}')
        return png()


def test_decimal_rates_and_long_context_boundary():
    assert charge("gpt-6.1-sol", 10000, 20000) == 220000
    assert charge("gpt-6.1-terra", 272000, 1) == 272005
    assert charge("gpt-6.1-terra", 272001, 1) == Decimal("544009.5")


@pytest.mark.parametrize("inputs,outputs", [(None, 1), (-1, 0), (1, True), (1.5, 0)])
def test_unknown_usage_is_fatal(inputs, outputs):
    with pytest.raises(ValueError):
        charge("gpt-6.1-sol", inputs, outputs)


def test_accounting_includes_incomplete_and_full_cached_input():
    b = Budget()
    response = SimpleNamespace(
        status="incomplete",
        usage=SimpleNamespace(
            input_tokens=10000, output_tokens=20000, input_tokens_details=SimpleNamespace(cached_tokens=9999)
        ),
    )
    b.consume("gpt-6.1-sol", response)
    assert b.calls == 1 and b.spent == 220000


def test_no_reservation_beyond_credit_or_call_cap():
    b = Budget()
    assert b.allows("gpt-6.1-sol", 1000, 1000)
    assert not b.allows("gpt-6-astra", 100000, 100000)
    b.calls = 60
    assert not b.allows("gpt-6-luna", 1, 1)


def test_full_pipeline_replays_same_calls_renders_and_output():
    first, replay = FakeWitness(), FakeWitness()
    a = asyncio.run(generate(png(), 987654321, first))
    b = asyncio.run(generate(png(), 987654321, replay))
    assert a == b and a is not None
    assert first.trace == replay.trace
    ids = [entry[1]["request_id"] for entry in first.trace if entry[0] == "call"]
    assert len(ids) == len(set(ids)) and len(ids) <= 60
    for kind, *rest in first.trace:
        if kind == "call":
            assert rest[0]["service_tier"] == "default"
        else:
            assert rest[1].lighting == "neutral"
    assert any(entry[0] == "render" and entry[1] == a for entry in first.trace)


def test_transport_failure_propagates_for_runtime_recovery():
    with pytest.raises(ConnectionError):
        asyncio.run(generate(png(), 1, FakeWitness(error=ConnectionError("capture uncertain"))))


def test_structured_render_rejection_gets_unique_bounded_repair():
    witness = FakeWitness(reject=True)
    search = Search(png(), 3, witness)
    result = asyncio.run(search.build(10))
    assert result is not None
    ids = [entry[1]["request_id"] for entry in witness.trace if entry[0] == "call"]
    assert ids == [10, 10010]


def test_no_valid_candidate_returns_explicit_none():
    assert asyncio.run(generate(png(), 3, FakeWitness(invalid=True))) is None


def test_tied_comparison_keeps_incumbent_in_both_label_orders():
    witness = FakeWitness()
    search = Search(png(), 9, witness)
    parent = Candidate("parent", png(), SOURCE)
    child = Candidate("child", png(), SOURCE)
    result, _ = asyncio.run(search.select([parent, child], 400))
    assert result is parent
    calls = [item[1] for item in witness.trace if item[0] == "call"]
    assert [c["request_id"] for c in calls] == [400, 401]


@pytest.mark.parametrize("mutation", ["duplicate", "nan", "bool", "missing"])
def test_malformed_selector_cannot_replace_incumbent(mutation):
    row = {"label": "A", "front": [0, 0, 0, 0], "feature_hits": 7, "artifact": 0, "bad_sides": 0, "fixes": ""}
    other = dict(row, label="B")
    if mutation == "duplicate":
        other["label"] = "A"
    elif mutation == "nan":
        row["front"][0] = float("nan")
    elif mutation == "bool":
        row["bad_sides"] = True
    else:
        del row["artifact"]
    with pytest.raises((ValueError, KeyError)):
        parse_scores(json.dumps({"scores": [row, other]}), {"A": 0, "B": 1})


def test_normalization_keeps_helpers_and_single_export():
    source = normalize(SOURCE + "\nfunction helper(THREE) { return new THREE.Vector3(); }")
    assert source.count("export default") == 1
    assert "function helper(THREE)" in source and "0.98 / extent" in source
    assert source == normalize(SOURCE + "\nfunction helper(THREE) { return new THREE.Vector3(); }")


def test_markdown_module_is_unwrapped():
    assert normalize("```js\n" + SOURCE + "\n```") == normalize(SOURCE)


def test_beam_keeps_different_geometric_lineages():
    search = Search(png(), 9, FakeWitness())
    candidates = [Candidate(str(i), png(), SOURCE, lineage) for i, lineage in enumerate((10, 10, 11, 12))]
    result = asyncio.run(search.rank(candidates, 100, keep=3, distinct_lineages=True))
    assert [c.lineage for c, _ in result] == [10, 11, 12]


def test_parallel_stage_reserves_all_dispatched_outputs_before_awaiting():
    witness = FakeWitness()
    search = Search(png(), 9, witness)
    # One Astra call fits, two cannot fit even though fake responses are cheap.
    search.budget.spent = Decimal(1600000)
    parents = [(Candidate(str(i), png(), SOURCE, i), "") for i in range(3)]
    children = asyncio.run(search.improve_stage(parents, 400, model="gpt-6-astra", reserve=1000000))
    ids = [v[1]['request_id'] for v in witness.trace if v[0] == 'call']
    assert ids == [400]
    assert len(children) == 1


def test_late_improvements_receive_the_selected_preceding_source(monkeypatch):
    async def pick_latest(self, candidates, ident, *, keep=1, **kwargs):
        usable = [c for c in candidates if c is not None]
        return [(c, "Check proportions") for c in usable[-keep:]]

    monkeypatch.setattr(Search, 'rank', pick_latest)
    witness = FakeWitness()
    result = asyncio.run(generate(png(), 9, witness))
    calls = {v[1]['request_id']: v[1] for v in witness.trace if v[0] == 'call'}
    parent_text = lambda ident: '\n'.join(v.get('text', '') for v in calls[ident]['input'][0]['content'])
    assert '// draft 601' in parent_text(800)
    assert '// draft 800' in parent_text(1000)
    assert all(calls[i]['reasoning']['effort'] == 'xhigh' for i in (600, 601, 800, 1000))
    assert result is not None


def test_closeups_keep_all_four_views_and_dark_parts():
    image = Image.new('RGB', (400, 400), 'white')
    for x, y, color in ((50, 50, 'black'), (250, 50, 'red'), (50, 250, 'green'), (250, 250, 'blue')):
        image.paste(color, (x, y, x + 60, y + 80))
    b = io.BytesIO();image.save(b, 'PNG')
    with Image.open(io.BytesIO(front_closeups(b.getvalue()))) as out:
        assert out.size == (1152, 1152)
        assert [out.getpixel((x, y)) for x, y in ((288, 288), (864, 288), (288, 864), (864, 864))] == [(0, 0, 0), (255, 0, 0), (0, 128, 0), (0, 0, 255)]


def test_missing_reverse_order_cannot_replace_parent(monkeypatch):
    search = Search(png(), 9, FakeWitness())
    calls = []
    async def partial_call(ident, *args, **kwargs):
        calls.append(ident)
        if len(calls) == 2:
            return None
        labels = kwargs['schema']['properties']['scores']['items']['properties']['label']['enum']
        return json.dumps({'scores': [{'label': label, 'front': [0, 0, 0, 0],
            'feature_hits': 7, 'artifact': 0, 'bad_sides': 0, 'fixes': ''} for label in labels]})
    monkeypatch.setattr(search, 'call', partial_call)
    parent = Candidate('parent', png(), SOURCE, 1)
    child = Candidate('child', png(), SOURCE, 2)
    ranked = asyncio.run(search.rank([parent, child], 400))
    assert ranked == [(parent, '')]


@pytest.mark.parametrize('stretch', [(0, 1, 1), (1, float('nan'), 1), (1, -1, 1), (1, 1)])
def test_invalid_dimension_candidates_are_rejected(stretch):
    with pytest.raises(ValueError):
        normalize(SOURCE, stretch=stretch)


def test_identical_rendered_variants_do_not_consume_judge_calls():
    witness = FakeWitness()
    asyncio.run(generate(png(), 9, witness))
    ids = [v[1]['request_id'] for v in witness.trace if v[0] == 'call']
    assert not any(i in ids for i in (1300, 1301, 1400, 1401))
