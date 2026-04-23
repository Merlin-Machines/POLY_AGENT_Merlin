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
