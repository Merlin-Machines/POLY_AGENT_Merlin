"""Shared utilities for the poly_btc module (no external deps / no circular imports)."""
from __future__ import annotations

import json
import math
import re
from typing import Optional


def as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def parse_money_target(text: str) -> Optional[float]:
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*([kmb])?\b", text.lower())
    if not m:
        return None
    base = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix, 1)
    return base * mult


def ncdf(x: float) -> float:
    """Abramowitz & Stegun normal CDF approximation."""
    s = 1 if x >= 0 else -1
    x = abs(x)
    t = 1 / (1 + 0.2316419 * x)
    c = (0.31938153, -0.356563782, 1.781477937, -1.821255978, 1.330274429)
    poly = sum(c[i] * t ** (i + 1) for i in range(5))
    cdf = 1 - (1 / math.sqrt(2 * math.pi)) * math.exp(-x * x / 2) * poly
    return cdf if s > 0 else 1 - cdf


def snipe_resolution_prob(
    btc_price: float,
    target: float,
    seconds_to_expiry: float,
    candle_analysis: dict,
) -> tuple[float, float]:
    """
    Near-expiry resolution probability for BTC price markets.

    Returns (resolution_prob_yes, abs_gap_pct).
    resolution_prob_yes → probability that YES resolves (BTC hit / is above target).

    Logic:
      - BTC above target → YES resolves → high probability
      - BTC below target → NO resolves → low yes-probability
      - Certainty increases as |gap| grows and as time runs out
      - Candle momentum gives a small nudge in the direction of movement
    """
    if target <= 0 or btc_price <= 0:
        return 0.5, 0.0

    gap_pct = (btc_price - target) / target
    abs_gap = abs(gap_pct)

    # Base certainty from BTC distance to target
    if abs_gap >= 0.05:
        base_cert = 0.93
    elif abs_gap >= 0.02:
        base_cert = 0.82
    elif abs_gap >= 0.005:
        base_cert = 0.67
    else:
        base_cert = 0.52

    # Time pressure: certainty tightens as expiry approaches
    time_factor = max(0.0, 1.0 - seconds_to_expiry / 180.0)
    certainty = min(0.97, base_cert + time_factor * 0.04)

    # Candle momentum nudge (small — structural gap dominates)
    momentum = candle_analysis.get("momentum", 0.0)
    trend = candle_analysis.get("trend", "neutral")
    nudge = 0.0
    if gap_pct > 0:   # BTC above target, YES favoured
        if momentum > 0.25 or trend == "up":   nudge = +0.015
        elif momentum < -0.25 or trend == "down": nudge = -0.01
    else:             # BTC below target, NO favoured
        if momentum < -0.25 or trend == "down": nudge = -0.015
        elif momentum > 0.25 or trend == "up":  nudge = +0.01

    if gap_pct > 0:
        prob_yes = max(0.50, min(0.97, certainty + nudge))
    else:
        prob_yes = max(0.03, min(0.50, 1.0 - certainty + nudge))

    return prob_yes, abs_gap


def black_scholes_prob(
    current: float,
    target: float,
    T_years: float,
    vol: float = 0.65,
    direction_above: bool = True,
) -> float:
    """Probability that `current` crosses `target` within T_years at given vol."""
    if current <= 0 or target <= 0 or T_years <= 0:
        return 0.5
    d2 = math.log(current / target) / (vol * math.sqrt(T_years))
    raw = ncdf(d2) if direction_above else 1 - ncdf(d2)
    return max(0.05, min(0.95, raw))
