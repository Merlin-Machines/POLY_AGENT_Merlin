"""
Market-state classifier for BTC Polymarket markets.

Labels:
  resolved_like   — price ≥ 0.93 or ≤ 0.07; outcome essentially decided
  tilting         — price in 0.65-0.92 or 0.08-0.35; strongly one-sided
  flip_candidate  — price in 0.42-0.58; near 50/50, could move fast
  chaotic         — moderate spread (10-30%) or high short-term volatility
  dead_liquidity  — spread > 30% or liquidity < 100; don't trade
  normal          — everything else
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketStateResult:
    label: str        # see module docstring
    yes_price: float
    spread_pct: float
    liquidity: float
    confidence: float   # 0-1


def classify(
    yes_price: float,
    spread_data: Optional[dict],
    liquidity: float = 0.0,
    price_history: Optional[list[float]] = None,
) -> MarketStateResult:
    """Classify the current state of a Polymarket binary market."""
    spread_pct = float((spread_data or {}).get("spread_pct", 0.0) or 0.0)

    # Dead liquidity — nothing to trade against
    if liquidity < 100 or spread_pct > 0.30:
        return MarketStateResult(
            label="dead_liquidity",
            yes_price=yes_price,
            spread_pct=spread_pct,
            liquidity=liquidity,
            confidence=0.92,
        )

    # Essentially resolved — price already expresses near-certainty
    if yes_price >= 0.93 or yes_price <= 0.07:
        return MarketStateResult(
            label="resolved_like",
            yes_price=yes_price,
            spread_pct=spread_pct,
            liquidity=liquidity,
            confidence=0.88,
        )

    # High spread but not dead — volatile / thin book
    if spread_pct > 0.10:
        return MarketStateResult(
            label="chaotic",
            yes_price=yes_price,
            spread_pct=spread_pct,
            liquidity=liquidity,
            confidence=0.78,
        )

    # Near 50/50 — potential flip zone
    if 0.42 <= yes_price <= 0.58:
        velocity = 0.0
        if price_history and len(price_history) >= 2:
            velocity = abs(price_history[-1] - price_history[0]) / max(len(price_history) - 1, 1)
        conf = min(0.90, 0.70 + velocity * 5)
        return MarketStateResult(
            label="flip_candidate",
            yes_price=yes_price,
            spread_pct=spread_pct,
            liquidity=liquidity,
            confidence=conf,
        )

    # Strongly one-sided but not resolved
    if yes_price >= 0.65 or yes_price <= 0.35:
        return MarketStateResult(
            label="tilting",
            yes_price=yes_price,
            spread_pct=spread_pct,
            liquidity=liquidity,
            confidence=0.82,
        )

    return MarketStateResult(
        label="normal",
        yes_price=yes_price,
        spread_pct=spread_pct,
        liquidity=liquidity,
        confidence=0.60,
    )
