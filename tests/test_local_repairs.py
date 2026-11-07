import asyncio
import io
import json
import base64
import math
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from miner.alignment import foreground, similarity
from miner.pipeline import Candidate, Search, reference_closeup
from miner.surgery import apply_edits
from test_invariants import FakeWitness, SOURCE, png


def patch(edits):
    return json.dumps({'reason': 'Measured correction', 'edits': edits})


def test_edits_use_original_coordinates_even_when_replacement_contains_another_anchor():
    original = 'const width = 2; const height = 3;'
    edits = [{'old': 'const width = 2;', 'new': 'const height = 3; const width = 4;'},
             {'old': 'const height = 3;', 'new': 'const height = 5;'}]
    expected = 'const height = 3; const width = 4; const height = 5;'
    assert apply_edits(original, patch(edits)) == expected
    assert apply_edits(original, patch(list(reversed(edits)))) == expected


@pytest.mark.parametrize('original,edits', [
    ('const width = 2; const width = 2;', [{'old': 'const width = 2;', 'new': 'bad'}]),
    ('const width = 2;', [{'old': 'const height = 2;', 'new': 'bad'}]),
    ('const width = 2; const height = 3;', [{'old': 'const width = 2; const', 'new': 'bad'},
                                           {'old': '2; const height = 3;', 'new': 'bad'}]),
    ('const width = 2;', [{'old': '', 'new': 'bad'}]),
])
def test_ambiguous_missing_and_overlapping_edits_are_rejected(original, edits):
    with pytest.raises(ValueError):
        apply_edits(original, patch(edits))


def test_malformed_local_edit_preserves_the_previously_valid_model():
    # FakeWitness emits an edit anchored in a different draft: it must not apply.
    search = Search(png(), 42, FakeWitness())
    parent = Candidate('validated-parent', png(), SOURCE, detail=png())
    assert asyncio.run(search.surgical(parent, 'preserve good parts')) == [(parent, 'preserve good parts')]


def test_transport_failure_in_local_repair_is_not_converted_to_a_new_candidate():
    search = Search(png(), 42, FakeWitness(error=ConnectionError('capture pending')))
    parent = Candidate('validated-parent', png(), SOURCE, detail=png())
    with pytest.raises(ConnectionError):
        asyncio.run(search.surgical(parent, 'repair contour'))


def test_second_repair_cannot_spend_final_comparison_headroom():
    witness = FakeWitness()
    search = Search(png(), 42, witness)
    search.budget.spent = Decimal(4000000)
    parent = Candidate('validated-parent', png(), SOURCE, detail=png())
    result = asyncio.run(search.surgical(parent, 'repair contour', ident=2100, outputs=32768, reserve=500000))
    assert result == [(parent, 'repair contour')]
    assert witness.trace == []


def test_independent_drafts_are_not_given_an_arbitrary_incumbent_advantage():
    class VisualWitness:
        def __init__(self, red_front=None):
            self.responses = self
            self.red_front = red_front or [.95] * 4

        async def create(self, **request):
            rows, label = [], None
            for item in request['input'][0]['content']:
                if item['type'] == 'input_text' and item['text'].startswith('CANDIDATE '):
                    label = item['text'].removeprefix('CANDIDATE ')
                elif item['type'] == 'input_image' and label:
                    image = Image.open(io.BytesIO(base64.b64decode(item['image_url'].split(',')[1])))
                    front = self.red_front if image.getpixel((0, 0))[0] == 255 else [1.] * 4
                    rows.append({'label': label, 'front': front, 'feature_hits': 7,
                                 'artifact': 0, 'bad_sides': 0, 'fixes': 'Measured image comparison'})
                    label = None
            return SimpleNamespace(status='completed', output_text=json.dumps({'scores': rows}),
                                   usage=SimpleNamespace(input_tokens=1000, output_tokens=500))
    parent = Candidate('blue', image_bytes(Image.new('RGB', (8, 8), 'blue')), SOURCE)
    child = Candidate('red', image_bytes(Image.new('RGB', (8, 8), 'red')), SOURCE)
    search = Search(png(), 42, VisualWitness())
    assert asyncio.run(search.rank([parent, child], 100, incumbent=False))[0][0] is child
    assert asyncio.run(search.rank([parent, child], 200))[0][0] is parent
    # A consistent 0.15 gain per front view is below the scalar 0.18 switch
    # margin, but dominates the parent in every measured criterion and order.
    search = Search(png(), 42, VisualWitness([.85] * 4))
    assert asyncio.run(search.rank([parent, child], 300))[0][0] is child
    # One degraded view blocks that smaller step, even when its mean is better.
    search = Search(png(), 42, VisualWitness([1.1, .85, .85, .85]))
    assert asyncio.run(search.rank([parent, child], 400))[0][0] is parent


def test_mixed_model_drafts_are_charged_at_their_actual_model_rates():
    search = Search(png(), 42, FakeWitness())
    candidates = asyncio.run(search.initials())
    assert len(candidates) == 5
    # 2 Terra at 3500, 2 Sol at 7000, 1 Astra at 35000 per fake usage.
    assert search.budget.spent == 56000
    assert search.budget.calls == 5


def image_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def test_reference_detail_retains_thin_parts_and_always_supplements_the_full_photo():
    image = Image.new('RGB', (800, 800), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((400, 140, 403, 760), fill=(110, 70, 25))
    draw.rectangle((404, 140, 550, 300), fill='red')
    data = image_bytes(image)
    detail = reference_closeup(data)
    assert detail is not None
    with Image.open(io.BytesIO(detail)) as crop:
        assert max(crop.size) == 1152
        brown = [(x, y) for y in range(crop.height) for x in range(crop.width)
                 if crop.getpixel((x, y)) == (110, 70, 25)]
        assert brown and max(y for x, y in brown) > .90 * crop.height
    search = Search(data, 42, FakeWitness())
    images = [v['image_url'] for v in search.target() if v['type'] == 'input_image']
    assert len(images) == 2
    assert base64.b64decode(images[0].split(',')[1]) == search.image
    assert reference_closeup(png()) is None


def test_elevation_search_preserves_geometry_yaw_dimensions_and_incumbent(monkeypatch):
    search = Search(png(), 42, FakeWitness())
    parent = Candidate('already-validated-source', b'parent-sheet', SOURCE, lineage=7,
                       detail=png(), yaw=.4, stretch=(1.12, 1, .88))
    rendered, selections = [], []
    async def render(raw, **kwargs):
        rendered.append((raw, kwargs))
        return Candidate('variant-' + str(kwargs['pitch']), b'variant-sheet', raw,
                         lineage=kwargs['lineage'], pitch=kwargs['pitch'],
                         yaw=kwargs['yaw'], stretch=kwargs['stretch'])
    async def rank(candidates, ident, **kwargs):
        selections.append((candidates, ident, kwargs))
        return [(candidates[0], '')]
    monkeypatch.setattr(search, 'render', render)
    monkeypatch.setattr(search, 'rank', rank)
    assert asyncio.run(search.elevated(parent)) is parent
    assert 1 <= len(rendered) <= 3
    assert any(abs(v['pitch'] - math.pi / 4) < 1e-9 for raw, v in rendered)
    assert all(raw == parent.raw and v['yaw'] == parent.yaw and v['stretch'] == parent.stretch
               and v['lineage'] == parent.lineage for raw, v in rendered)
    assert selections[0][0][0] is parent and selections[0][1] == 2500


def test_alignment_compares_shape_without_rewarding_translation_or_canvas_fill():
    target = Image.new('RGB', (256, 256), 'white')
    ImageDraw.Draw(target).rectangle((80, 30, 175, 225), fill='black')
    grid = Image.new('RGB', (512, 512), 'white')
    wrong = grid.copy()
    for x, y in ((0, 0), (256, 0), (0, 256), (256, 256)):
        ImageDraw.Draw(grid).rectangle((x + 30, y + 50, x + 77, y + 147), fill='black')
        ImageDraw.Draw(wrong).rectangle((x + 30, y + 50, x + 127, y + 97), fill='black')
    correct = similarity(image_bytes(target), image_bytes(grid))
    incorrect = similarity(image_bytes(target), image_bytes(wrong))
    assert correct > .94 and correct > incorrect + .35
    assert foreground(png(), reference=True) is None
