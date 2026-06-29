from __future__ import annotations

_PRICING_PER_MTK: list[tuple[str, float, float]] = [
    ("claude-fable-5", 10.00, 50.00),
    ("claude-mythos-5", 10.00, 50.00),
    ("claude-opus-4-8", 5.00, 25.00),
    ("claude-opus-4-7", 5.00, 25.00),
    ("claude-opus-4-6", 5.00, 25.00),
    ("claude-opus-4-5", 5.00, 25.00),
    ("claude-sonnet-4-6", 3.00, 15.00),
    ("claude-sonnet-4-5", 3.00, 15.00),
    ("claude-haiku-4-5", 1.00, 5.00),
]

_MTK = 1_000_000


def calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return the USD cost for a session given model and token counts.

    Uses prefix matching so dated snapshot variants (e.g. claude-opus-4-8-20260101)
    resolve to the correct pricing row. Returns 0.0 for unknown models.
    """
    for prefix, input_rate, output_rate in _PRICING_PER_MTK:
        if model.startswith(prefix):
            return (tokens_in * input_rate + tokens_out * output_rate) / _MTK
    return 0.0
