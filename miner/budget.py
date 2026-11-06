"""Per-invocation accounting at the frozen competition tariff, including reasoning."""

import json
from decimal import Decimal
from pathlib import Path

PRICING = json.loads(Path(__file__).with_name("pricing.json").read_text())
LIMIT = Decimal(PRICING["credits_per_prompt"])
CALL_LIMIT = PRICING["calls_per_prompt"]


def charge(model, inputs, outputs):
    if type(inputs) is not int or type(outputs) is not int or min(inputs, outputs) < 0:
        raise ValueError("Missing or invalid verified token usage")
    row = PRICING["models"][model]
    prefix = "long_" if inputs > PRICING["long_context_above_input_tokens"] else ""
    return (
        Decimal(str(row[prefix + "input_credits_per_token"])) * inputs
        + Decimal(str(row[prefix + "output_credits_per_token"])) * outputs
    )


def input_bound(instructions, content, schema=None):
    # Intentionally conservative: UTF-8 byte count (not chars/4), 16K tokens per
    # bounded image, and protocol/schema allowance. Images are resized to <=1152.
    text = len(instructions.encode("utf-8")) + 4096
    for item in content:
        if item["type"] == "input_text":
            text += len(item["text"].encode("utf-8"))
        else:
            text += 16384
    if schema:
        text += len(json.dumps(schema).encode("utf-8"))
    return text


class Budget:
    def __init__(self):
        self.spent = Decimal(0)
        self.calls = 0

    def allows(self, model, inputs, outputs, reserve=0):
        return (
            self.calls < CALL_LIMIT and self.spent + charge(model, inputs, outputs) + Decimal(reserve) <= LIMIT - 100000
        )

    def consume(self, model, response):
        usage = response.usage
        if usage is None:
            raise ValueError("Response has no verified usage; cannot safely continue")
        self.spent += charge(model, usage.input_tokens, usage.output_tokens)
        self.calls += 1
        if self.spent > LIMIT or self.calls > CALL_LIMIT:
            raise ValueError("Competition budget exceeded")
