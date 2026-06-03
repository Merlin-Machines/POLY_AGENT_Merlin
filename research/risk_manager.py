"""
research/risk_manager.py — disciplined risk controls (Silver-Fox lineage).

Provides:
  • Fractional-Kelly position sizing on binary contract edge
  • ATR-as-volatility-context scalar (reduces size in turbulent regimes)
  • Max-drawdown circuit breaker
  • Daily loss limit
  • Consecutive-loss cooldown

IMPORTANT design rule (carried over from the Chimera mashup):
ATR is NOT used to set a stop-loss/take-profit *price* on a Polymarket token —
a token price is not spot BTC. ATR only scales position size and can veto entries
when volatility is extreme.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SizingResult:
    size_usdc: float
    kelly_fraction: float
    atr_scalar: float
    reason: str


class RiskManager:
    def __init__(
        self,
        kelly_fraction: float = 0.25,
        max_position_pct: float = 0.05,
        max_drawdown_pct: float = 15.0,
        daily_loss_pct: float = 5.0,
        cooldown_losses: int = 3,
        atr_veto_pct: float = 6.0,
        min_size_usdc: float = 1.0,
        max_size_usdc: float = 25.0,
    ):
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_pct = daily_loss_pct
        self.cooldown_losses = cooldown_losses
        self.atr_veto_pct = atr_veto_pct
        self.min_size_usdc = min_size_usdc
        self.max_size_usdc = max_size_usdc

        self.peak_value: float | None = None
        self.daily_start_value: float | None = None
        self.consecutive_losses = 0

    # ── Sizing ────────────────────────────────────────────────────────────────
    def size_position(
        self,
        edge: float,
        our_prob: float,
        bankroll: float,
        atr_pct: float = 2.0,
    ) -> SizingResult | None:
        """
        Fractional-Kelly size on a binary edge, scaled by an ATR volatility factor.
        Returns None if the trade should be vetoed (extreme volatility).
        """
        if atr_pct >= self.atr_veto_pct:
            return None
        if edge <= 0 or not (0.0 < our_prob < 1.0):
            return SizingResult(self.min_size_usdc, 0.0, 1.0, "min_size_floor")

        loss_prob = 1.0 - our_prob
        b = our_prob / (loss_prob + 1e-9)
        kelly = max(0.0, (our_prob * b - loss_prob) / (b + 1e-9))

        atr_scalar = self._atr_scalar(atr_pct)
        raw = bankroll * kelly * self.kelly_fraction * atr_scalar
        capped = min(raw, bankroll * self.max_position_pct, self.max_size_usdc)
        size = max(self.min_size_usdc, round(capped, 2))
        return SizingResult(size, round(kelly, 4), round(atr_scalar, 3), "kelly_sized")

    def _atr_scalar(self, atr_pct: float) -> float:
        if atr_pct <= 1.5:
            return 1.0
        if atr_pct >= 4.0:
            return 0.5
        return 1.0 - 0.5 * ((atr_pct - 1.5) / 2.5)

    # ── Circuit breakers ──────────────────────────────────────────────────────
    def update_peak(self, portfolio_value: float) -> None:
        if self.peak_value is None or portfolio_value > self.peak_value:
            self.peak_value = portfolio_value
        if self.daily_start_value is None:
            self.daily_start_value = portfolio_value

    def record_trade_result(self, pnl: float) -> None:
        if pnl > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

    def reset_daily(self, portfolio_value: float) -> None:
        self.daily_start_value = portfolio_value

    def check_circuit_breakers(self, portfolio_value: float) -> tuple[bool, str]:
        self.update_peak(portfolio_value)

        if self.peak_value and self.peak_value > 0:
            dd = (self.peak_value - portfolio_value) / self.peak_value * 100
            if dd >= self.max_drawdown_pct:
                return False, f"max_drawdown:{dd:.1f}%>={self.max_drawdown_pct}%"

        if self.daily_start_value and self.daily_start_value > 0:
            daily = (portfolio_value - self.daily_start_value) / self.daily_start_value * 100
            if daily <= -self.daily_loss_pct:
                return False, f"daily_loss:{daily:.1f}%<=-{self.daily_loss_pct}%"

        if self.consecutive_losses >= self.cooldown_losses:
            return False, f"cooldown:{self.consecutive_losses}_consecutive_losses"

        return True, "ok"
