"""
Model prices in USD per 1M tokens (input, output). Used by the collector (cost per span),
the brain (budgets) and eval (ROI). Owners: Alif + Taseen.

Anthropic prices: first-party API list prices (Oct 2026). Simulated agents use "sim", priced like a
mid-size model so the demo numbers are realistic but still small.
"""
from __future__ import annotations

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "sim": (2.00, 10.00),
    "sim-model": (2.00, 10.00),
}
DEFAULT_PRICE = PRICES_PER_MTOK["sim"]


def price_for(model: str) -> tuple[float, float]:
    """Exact match first, then prefix match (e.g. 'claude-haiku-5-5-xyz'), else the default."""
    model = (model or "").lower()
    if model in PRICES_PER_MTOK:
        return PRICES_PER_MTOK[model]
    for name, price in PRICES_PER_MTOK.items():
        if model.startswith(name):
            return price
    return DEFAULT_PRICE


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = price_for(model)
    return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 8)
