"""
research/binary_market.py — binary Polymarket contract simulator.

Silver-Fox's PaperTrader modelled spot long-only positions. Polymarket contracts
are binary: you buy YES or NO shares at a price in (0, 1); each share pays $1 if
that outcome resolves true and $0 otherwise. This module models that economics so
backtests reflect how Merlin actually makes money.

Entry:   cost  = shares * entry_price        (shares = size_usdc / entry_price)
Exit:    proceeds = shares * exit_price       (exit at a later market price, or 0/1 at resolution)
P&L:     proceeds - cost = shares * (exit_price - entry_price)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BinaryTrade:
    side: str               # "YES" | "NO"
    entry_price: float
    exit_price: float
    shares: float
    size_usdc: float
    pnl_usd: float
    pnl_pct: float
    reason: str = ""


@dataclass
class BinaryPaperTrader:
    """Single-position binary contract paper trader for backtesting."""
    starting_balance: float = 1000.0
    fee_pct: float = 0.0          # Polymarket has no maker fee; taker ~0
    balance: float = field(init=False)
    open_side: str | None = field(default=None, init=False)
    open_price: float = field(default=0.0, init=False)
    open_shares: float = field(default=0.0, init=False)
    open_cost: float = field(default=0.0, init=False)
    trades: list[BinaryTrade] = field(default_factory=list, init=False)

    def __post_init__(self):
        self.balance = self.starting_balance

    @property
    def in_position(self) -> bool:
        return self.open_side is not None

    def open(self, side: str, entry_price: float, size_usdc: float) -> bool:
        if self.in_position:
            return False
        entry_price = max(0.01, min(0.99, float(entry_price)))
        size_usdc = min(size_usdc, self.balance)
        if size_usdc <= 0:
            return False
        shares = size_usdc / entry_price
        cost = shares * entry_price * (1 + self.fee_pct)
        self.balance -= cost
        self.open_side = side
        self.open_price = entry_price
        self.open_shares = shares
        self.open_cost = cost
        return True

    def close(self, exit_price: float, reason: str = "") -> BinaryTrade | None:
        if not self.in_position:
            return None
        exit_price = max(0.0, min(1.0, float(exit_price)))
        proceeds = self.open_shares * exit_price * (1 - self.fee_pct)
        self.balance += proceeds
        pnl = proceeds - self.open_cost
        pnl_pct = (pnl / self.open_cost * 100) if self.open_cost else 0.0
        trade = BinaryTrade(
            side=self.open_side or "",
            entry_price=self.open_price,
            exit_price=exit_price,
            shares=self.open_shares,
            size_usdc=self.open_cost,
            pnl_usd=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
        )
        self.trades.append(trade)
        self.open_side = None
        self.open_price = 0.0
        self.open_shares = 0.0
        self.open_cost = 0.0
        return trade

    def portfolio_value(self, mark_price: float | None = None) -> float:
        """Cash + marked value of any open position."""
        if not self.in_position:
            return self.balance
        mark = mark_price if mark_price is not None else self.open_price
        mark = max(0.0, min(1.0, float(mark)))
        return self.balance + self.open_shares * mark

    def summary(self, final_mark: float | None = None) -> dict:
        closed = [t for t in self.trades]
        wins = [t for t in closed if t.pnl_usd > 0]
        pv = self.portfolio_value(final_mark)
        return {
            "final_value": round(pv, 2),
            "pnl_usd": round(pv - self.starting_balance, 2),
            "pnl_pct": round((pv / self.starting_balance - 1) * 100, 2),
            "total_trades": len(closed),
            "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
            "avg_win_pct": round(sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else 0.0,
            "avg_loss_pct": round(
                sum(t.pnl_pct for t in closed if t.pnl_usd <= 0)
                / max(1, len(closed) - len(wins)), 2
            ) if closed else 0.0,
        }
