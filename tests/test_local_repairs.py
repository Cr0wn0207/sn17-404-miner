import asyncio
import io
import json
from decimal import Decimal

import pytest
from PIL import Image, ImageDraw

from miner.alignment import foreground, similarity
from miner.pipeline import Candidate, Search
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


def image_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


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
