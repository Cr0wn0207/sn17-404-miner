"""Apply bounded, non-overlapping source edits against one immutable snapshot."""

import json


PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "edits": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                "required": ["old", "new"], "additionalProperties": False,
            },
        },
    },
    "required": ["reason", "edits"], "additionalProperties": False,
}


def apply_edits(source, payload):
    """Reject ambiguity and overlapping edits; inserted text is never searched again."""
    patch = json.loads(payload)
    if not isinstance(patch, dict) or set(patch) != {"reason", "edits"}:
        raise ValueError("Invalid edit envelope")
    if not isinstance(patch["reason"], str) or not isinstance(patch["edits"], list) or len(patch["edits"]) > 8:
        raise ValueError("Invalid edit list")
    spans = []
    for edit in patch["edits"]:
        if not isinstance(edit, dict) or set(edit) != {"old", "new"}:
            raise ValueError("Invalid edit")
        old, new = edit["old"], edit["new"]
        if not isinstance(old, str) or not isinstance(new, str) or len(old) < 12 or source.count(old) != 1:
            raise ValueError("Edit anchor must identify one original fragment")
        start = source.index(old)
        spans.append((start, start + len(old), new))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("Overlapping original fragments")
    for start, end, new in reversed(spans):
        source = source[:start] + new + source[end:]
    if len(source.encode("utf-8")) > 1048576:
        raise ValueError("Edited module exceeds the source headroom")
    return source
