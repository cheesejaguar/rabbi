"""Single source of truth for model prices (USD per 1M tokens).

Both the admin cost dashboard and ``docs/unit_economics.py`` read prices
from here so that reported spend and the business plan cannot drift apart.
Update this table when list prices change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00, 0.20, 2.50, 4.00),
    "claude-sonnet-5": ModelPrice(2.00, 10.00, 0.20, 2.50, 4.00),
    "claude-opus-5-5": ModelPrice(4.00, 20.00, 0.20, 5.00, 8.00),
    "claude-haiku-5-5": ModelPrice(0.10, 0.50, 0.01, 0.125, 0.20),
    # Legacy gateway identifiers used by the v1 pipeline.
    "anthropic/claude-sonnet-5": ModelPrice(2.00, 10.00, 0.20, 2.50, 4.00),
    "anthropic/claude-sonnet-4-20250514": ModelPrice(3.00, 15.00, 0.30, 3.75, 6.00),
}

DEFAULT_PRICE = PRICES["claude-sonnet-5-5"]


def price_for(model: str) -> ModelPrice:
    return PRICES.get(model, DEFAULT_PRICE)


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
) -> float:
    """Estimated USD cost of one call. ``input_tokens`` excludes cached tokens."""
    p = price_for(model)
    total = (
        input_tokens * p.input
        + output_tokens * p.output
        + cache_read_tokens * p.cache_read
        + cache_write_5m_tokens * p.cache_write_5m
        + cache_write_1h_tokens * p.cache_write_1h
    ) / 1_000_000
    return round(total, 6)


def usage_cost(model: str, usage) -> dict:
    """Normalize an Anthropic ``usage`` object into a metrics dict with cost."""
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                "cache_write_tokens": 0, "estimated_cost_usd": 0.0}
    get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
    inp = get("input_tokens") or 0
    out = get("output_tokens") or 0
    read = get("cache_read_input_tokens") or 0
    write_total = get("cache_creation_input_tokens") or 0
    w1h = 0
    breakdown = get("cache_creation")
    if breakdown is not None:
        bget = (lambda k: breakdown.get(k)) if isinstance(breakdown, dict) else (lambda k: getattr(breakdown, k, None))
        w1h = bget("ephemeral_1h_input_tokens") or 0
    w5m = max(0, write_total - w1h)
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": read,
        "cache_write_tokens": write_total,
        "estimated_cost_usd": cost_usd(model, inp, out, read, w5m, w1h),
    }
