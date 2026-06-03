"""
research/backtest.py — walk-forward backtest on BINARY Polymarket economics.

Pipeline per bar (mirrors the live agent's gating order):
  features  →  technical_signal  →  ML approval  →  risk sizing / circuit breakers
            →  binary contract open  →  resolve after a forward horizon

How a crypto signal becomes a binary trade
------------------------------------------
A BUY (bullish) signal opens a YES contract on "price higher in H bars".
A SELL (bearish) signal opens a YES contract on "price lower in H bars".
The contract is bought at a modelled market price (default 0.50 — an efficient
coin-flip market) and resolves to 1.0 if the move played out, else 0.0.
P&L = shares * (resolution - entry_price). Edge therefore comes purely from the
signal being right more often than the entry price implies.

Usage:
    python -m research.backtest
    python -m research.backtest --pair ETH-USD --horizon 6 --entry-price 0.5
"""
from __future__ import annotations

import argparse
import sys
import os

# Allow running as `python research/backtest.py` or `python -m research.backtest`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import build_feature_snapshot, technical_signal, FEATURE_COLS
from utils.ml_filter import MLFilter
from research.candles import load_candles, trailing_window
from research.binary_market import BinaryPaperTrader
from research.risk_manager import RiskManager


def _confidence_edge(features: dict, signal: str) -> float:
    """Translate signal strength into an estimated win-prob edge over 0.5."""
    rsi = float(features.get("rsi14", 50.0) or 50.0)
    spread = abs(float(features.get("ema9_21_spread", 0.0) or 0.0))
    # Stronger EMA separation + RSI room → more conviction (cap at +0.18 edge)
    base = min(spread * 4.0, 0.12)
    if signal == "BUY":
        rsi_room = max(0.0, (70 - rsi) / 70)
    else:
        rsi_room = max(0.0, (rsi - 30) / 70)
    return round(min(base + rsi_room * 0.06, 0.18), 4)


def run_backtest(
    product_id: str = "BTC-USD",
    granularity: int = 3600,
    bars: int = 2000,
    horizon: int = 6,
    entry_price: float = 0.50,
    ml_threshold: float = 0.55,
    starting_balance: float = 1000.0,
    warmup: int = 60,
    verbose: bool = True,
) -> dict:
    candles = load_candles(product_id, granularity, bars)
    n = len(candles)
    if n < warmup + horizon + 10:
        raise ValueError(f"Not enough candles ({n}) for backtest")

    trader = BinaryPaperTrader(starting_balance=starting_balance)
    rm = RiskManager()
    ml = MLFilter()
    ml_ready = ml.load()
    ml_approvals = ml_rejections = 0

    closes = [c["close"] for c in candles]
    equity: list[float] = []
    peak = starting_balance
    drawdowns: list[float] = []
    pending: dict | None = None  # {resolve_idx, side, correct_if}

    for i in range(warmup, n - 1):
        price_now = closes[i]
        pv = trader.portfolio_value(entry_price if trader.in_position else None)
        rm.update_peak(pv)

        # Resolve a matured contract
        if pending and i >= pending["resolve_idx"]:
            moved_up = closes[pending["resolve_idx"]] > closes[pending["entry_idx"]]
            won = moved_up if pending["side"] == "UP" else (not moved_up)
            resolution = 1.0 if won else 0.0
            t = trader.close(resolution, reason="resolved")
            if t:
                rm.record_trade_result(t.pnl_usd)
            pending = None

        if trader.in_position:
            equity.append(trader.portfolio_value(entry_price))
            peak = max(peak, equity[-1])
            drawdowns.append((equity[-1] - peak) / peak * 100)
            continue

        # Fresh signal on a bounded trailing window (O(W), not O(i))
        feats = build_feature_snapshot(trailing_window(candles, i))
        sig, _ = technical_signal(feats)

        if sig in ("BUY", "SELL"):
            ok_cb, _ = rm.check_circuit_breakers(pv)
            ml_ok = True
            if ml_ready:
                ml_ok, prob, _ = ml.approve(feats, FEATURE_COLS, threshold=ml_threshold)
                if ml_ok:
                    ml_approvals += 1
                else:
                    ml_rejections += 1

            if ok_cb and ml_ok:
                edge = _confidence_edge(feats, sig)
                our_prob = min(0.5 + edge, 0.95)
                atr_pct = float(feats.get("atr_pct", 2.0) or 2.0)
                sizing = rm.size_position(edge, our_prob, pv, atr_pct)
                if sizing is not None and edge > 0:
                    side = "UP" if sig == "BUY" else "DOWN"
                    if trader.open(
                        "YES" if side == "UP" else "NO",
                        entry_price,
                        sizing.size_usdc,
                    ):
                        pending = {
                            "entry_idx": i,
                            "resolve_idx": min(i + horizon, n - 1),
                            "side": side,
                        }

        equity.append(trader.portfolio_value(entry_price if trader.in_position else None))
        peak = max(peak, equity[-1])
        drawdowns.append((equity[-1] - peak) / peak * 100)

    # Force-close any open contract at the final realized outcome
    if trader.in_position and pending:
        moved_up = closes[-1] > closes[pending["entry_idx"]]
        won = moved_up if pending["side"] == "UP" else (not moved_up)
        trader.close(1.0 if won else 0.0, reason="final")

    summary = trader.summary(entry_price)
    max_dd = min(drawdowns) if drawdowns else 0.0
    summary["max_drawdown_pct"] = round(max_dd, 2)
    summary["ml_pass_rate"] = (
        round(ml_approvals / max(1, ml_approvals + ml_rejections) * 100, 1) if ml_ready else None
    )
    summary["product"] = product_id
    summary["horizon_bars"] = horizon
    summary["entry_price"] = entry_price
    summary["candles"] = n

    if verbose:
        _print(summary, ml_ready)
    return summary


def _print(s: dict, ml_ready: bool) -> None:
    print("\n" + "=" * 56)
    print(f"  Binary Backtest — {s['product']}  ({s['candles']} bars)")
    print("=" * 56)
    print(f"  {'Final value':<22}: ${s['final_value']:>12,.2f}")
    print(f"  {'Total P&L':<22}: {s['pnl_pct']:>+11.2f}%  (${s['pnl_usd']:+,.2f})")
    print(f"  {'Max drawdown':<22}: {s['max_drawdown_pct']:>+11.2f}%")
    print(f"  {'Win rate':<22}: {s['win_rate_pct']:>11.1f}%")
    print(f"  {'Avg win / loss':<22}: {s['avg_win_pct']:>+6.2f}% / {s['avg_loss_pct']:+.2f}%")
    print(f"  {'Total trades':<22}: {s['total_trades']:>12}")
    print(f"  {'Horizon / entry':<22}: {s['horizon_bars']} bars @ {s['entry_price']:.2f}")
    if ml_ready:
        print(f"  {'ML pass rate':<22}: {s['ml_pass_rate']:>11}%")
    else:
        print(f"  {'ML filter':<22}: {'not trained (pass-through)':>26}")
    print("=" * 56 + "\n")


def main():
    p = argparse.ArgumentParser(description="Binary Polymarket backtest")
    p.add_argument("--pair", default="BTC-USD")
    p.add_argument("--granularity", type=int, default=3600)
    p.add_argument("--bars", type=int, default=2000)
    p.add_argument("--horizon", type=int, default=6)
    p.add_argument("--entry-price", type=float, default=0.50)
    p.add_argument("--ml-threshold", type=float, default=0.55)
    args = p.parse_args()
    run_backtest(
        product_id=args.pair,
        granularity=args.granularity,
        bars=args.bars,
        horizon=args.horizon,
        entry_price=args.entry_price,
        ml_threshold=args.ml_threshold,
    )


if __name__ == "__main__":
    main()
