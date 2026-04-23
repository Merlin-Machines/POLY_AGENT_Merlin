"""
Fill model for the poly_btc pack.

Used for:
  • Dry-run fill simulation (more realistic than "always filled")
  • Pre-trade decision gates: should we use FOK vs LIMIT here?
  • Backtest realism: per-tick fill probability vs spread/liquidity

Does NOT affect live order placement — executor.py handles that via py_clob_client.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class FillResult:
    filled: bool
    fill_price: float
    fill_shares: float
    delay_ms: int
    miss_reason: Optional[str]   # None when filled


class FillModel:
    """
    Simulate order fill probability and price impact for each order type.

    Assumptions per type:
      FOK   — must fill fully or not at all; sensitive to spread and depth
      FAK   — fills available depth, kills rest; partial fills counted
      LIMIT — resting order; fills when market comes to us; slower, higher prob
      TAKER — immediate cross; nearly always fills but worst price
    """

    def simulate(
        self,
        order_type: str,
        price: float,
        size_usdc: float,
        spread_pct: float,
        liquidity: float,
        tif: str = "IOC",
    ) -> FillResult:
        dispatch = {
            "FOK": self.simulate_fok,
            "FAK": self.simulate_fak,
            "LIMIT": self.simulate_limit,
            "TAKER": self.simulate_taker,
        }
        fn = dispatch.get(order_type.upper(), self.simulate_taker)
        return fn(price, size_usdc, spread_pct, liquidity)

    # ---------------------------------------------------------------- per-type
    def simulate_fok(self, price, size_usdc, spread_pct, liquidity) -> FillResult:
        """FOK: all-or-nothing. High spread / thin book → miss."""
        delay = self._taker_delay_ms(spread_pct)
        prob = self._taker_fill_prob(spread_pct, liquidity, size_usdc)
        if random.random() < prob:
            fill_price = price * (1.0 + spread_pct * 0.5)
            shares = size_usdc / max(fill_price, 0.01)
            return FillResult(True, round(fill_price, 4), round(shares, 4), delay, None)
        return FillResult(False, price, 0.0, delay, "fok_no_liquidity")

    def simulate_fak(self, price, size_usdc, spread_pct, liquidity) -> FillResult:
        """FAK: fill available depth, kill rest. Partial is OK."""
        delay = self._taker_delay_ms(spread_pct)
        frac = self._partial_fill_fraction(liquidity, size_usdc)
        if frac > 0.1:
            fill_price = price * (1.0 + spread_pct * 0.4)
            filled_usdc = size_usdc * frac
            shares = filled_usdc / max(fill_price, 0.01)
            return FillResult(True, round(fill_price, 4), round(shares, 4), delay, None)
        return FillResult(False, price, 0.0, delay, "fak_insufficient_depth")

    def simulate_limit(self, price, size_usdc, spread_pct, liquidity) -> FillResult:
        """LIMIT resting order: fills if market moves to us. Slower but better price."""
        delay = self._limit_delay_ms(spread_pct)
        prob = max(0.20, 1.0 - spread_pct * 3.0)
        if random.random() < prob:
            shares = size_usdc / max(price, 0.01)
            return FillResult(True, price, round(shares, 4), delay, None)
        return FillResult(False, price, 0.0, delay, "limit_no_cross")

    def simulate_taker(self, price, size_usdc, spread_pct, liquidity) -> FillResult:
        """TAKER market order: almost always fills, worst price."""
        delay = self._taker_delay_ms(spread_pct)
        prob = self._taker_fill_prob(spread_pct, liquidity, size_usdc)
        if random.random() < prob:
            fill_price = price * (1.0 + spread_pct * 0.6)
            shares = size_usdc / max(fill_price, 0.01)
            return FillResult(True, round(fill_price, 4), round(shares, 4), delay, None)
        return FillResult(False, price, 0.0, delay, "taker_no_depth")

    # ---------------------------------------------------------------- helpers
    def _taker_fill_prob(self, spread_pct: float, liquidity: float, size_usdc: float) -> float:
        base = 0.85
        if spread_pct > 0.20:
            base -= 0.30
        elif spread_pct > 0.10:
            base -= 0.15
        if liquidity < 200:
            base -= 0.20
        elif liquidity < 500:
            base -= 0.08
        size_penalty = min(0.15, size_usdc / 500.0)
        return max(0.05, min(0.95, base - size_penalty))

    def _partial_fill_fraction(self, liquidity: float, size_usdc: float) -> float:
        if liquidity <= 0 or size_usdc <= 0:
            return 0.0
        return min(1.0, (liquidity * 0.01) / size_usdc)

    def _taker_delay_ms(self, spread_pct: float) -> int:
        base = 250 + (500 if spread_pct > 0.15 else 0)
        return base + random.randint(0, 200)

    def _limit_delay_ms(self, spread_pct: float) -> int:
        return 1500 + random.randint(0, 2000)
