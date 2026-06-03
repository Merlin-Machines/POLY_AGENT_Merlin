"""
research/optimizer.py — Optuna search over signal + risk parameters.

Maximises a risk-adjusted objective (P&L% penalised by drawdown and thin trade
counts) of the BINARY backtest. Writes the best parameters to
research/best_params.json for you to fold into the live config.

Degrades gracefully if optuna is not installed (prints install hint and exits).

Usage:
    python -m research.optimizer --trials 100
    python -m research.optimizer --trials 200 --pair ETH-USD
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import build_feature_snapshot, technical_signal, FEATURE_COLS
from research.candles import load_candles, trailing_window
from research.binary_market import BinaryPaperTrader
from research.risk_manager import RiskManager


def precompute_features(candles, warmup=60):
    """
    Build the feature snapshot for every bar ONCE. Feature values are independent
    of the searched parameters, so this is hoisted out of the trial loop — turning
    an O(trials x bars^2) search into O(bars^2 + trials x bars).
    """
    feats_by_bar: dict[int, dict] = {}
    n = len(candles)
    for i in range(warmup, n - 1):
        feats_by_bar[i] = build_feature_snapshot(trailing_window(candles, i))
    return feats_by_bar


def _simulate(candles, feats_by_bar, horizon, entry_price, rsi_ob, rsi_os,
              kelly_fraction, max_dd, cooldown, warmup=60):
    """Lightweight binary sim returning (pnl_pct, max_drawdown_pct, n_trades)."""
    closes = [c["close"] for c in candles]
    n = len(candles)
    trader = BinaryPaperTrader(starting_balance=1000.0)
    rm = RiskManager(kelly_fraction=kelly_fraction, max_drawdown_pct=max_dd,
                     cooldown_losses=cooldown)
    pending = None
    peak = 1000.0
    worst_dd = 0.0

    for i in range(warmup, n - 1):
        pv = trader.portfolio_value(entry_price if trader.in_position else None)
        rm.update_peak(pv)
        peak = max(peak, pv)
        worst_dd = min(worst_dd, (pv - peak) / peak * 100)

        if pending and i >= pending["resolve_idx"]:
            moved_up = closes[pending["resolve_idx"]] > closes[pending["entry_idx"]]
            won = moved_up if pending["side"] == "UP" else (not moved_up)
            t = trader.close(1.0 if won else 0.0)
            if t:
                rm.record_trade_result(t.pnl_usd)
            pending = None
        if trader.in_position:
            continue

        feats = feats_by_bar[i]
        sig, _ = technical_signal(feats, rsi_overbought=rsi_ob, rsi_oversold=rsi_os)
        if sig not in ("BUY", "SELL"):
            continue
        ok, _ = rm.check_circuit_breakers(pv)
        if not ok:
            continue
        rsi = float(feats.get("rsi14", 50.0) or 50.0)
        spread = abs(float(feats.get("ema9_21_spread", 0.0) or 0.0))
        edge = min(spread * 4.0, 0.15)
        if edge <= 0:
            continue
        our_prob = min(0.5 + edge, 0.95)
        atr_pct = float(feats.get("atr_pct", 2.0) or 2.0)
        sizing = rm.size_position(edge, our_prob, pv, atr_pct)
        if sizing is None:
            continue
        side = "UP" if sig == "BUY" else "DOWN"
        if trader.open("YES" if side == "UP" else "NO", entry_price, sizing.size_usdc):
            pending = {"entry_idx": i, "resolve_idx": min(i + horizon, n - 1), "side": side}

    s = trader.summary(entry_price)
    return s["pnl_pct"], worst_dd, s["total_trades"]


def run(n_trials=100, product_id="BTC-USD", granularity=3600, bars=2000):
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except Exception:
        print("\n  optuna not installed. Run:  pip install optuna\n")
        return None

    candles = load_candles(product_id, granularity, bars)
    print(f"\n  Optimising {product_id} on {len(candles)} bars ({n_trials} trials)…")
    print("  Precomputing features once…")
    feats_by_bar = precompute_features(candles)

    def objective(trial):
        horizon = trial.suggest_int("horizon", 3, 12)
        entry_price = trial.suggest_float("entry_price", 0.40, 0.60)
        rsi_ob = trial.suggest_int("rsi_overbought", 60, 80)
        rsi_os = trial.suggest_int("rsi_oversold", 20, 40)
        kelly = trial.suggest_float("kelly_fraction", 0.10, 0.50)
        max_dd = trial.suggest_float("max_drawdown_pct", 10.0, 30.0)
        cooldown = trial.suggest_int("cooldown_losses", 2, 6)

        pnl, dd, trades = _simulate(candles, feats_by_bar, horizon, entry_price,
                                    rsi_ob, rsi_os, kelly, max_dd, cooldown)
        if trades < 5:
            return -100.0
        # Risk-adjusted: reward P&L, penalise drawdown depth and thin samples
        thin_penalty = max(0, (15 - trades)) * 0.5
        return pnl + dd * 0.5 - thin_penalty  # dd is negative, so this subtracts

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_params
    best["_objective_value"] = round(study.best_value, 3)
    best["_product"] = product_id

    print(f"\n  Best objective: {study.best_value:.3f}")
    for k, v in best.items():
        if not k.startswith("_"):
            print(f"    {k:<18}: {v}")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best_params.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)
    print(f"\n  Saved → {out_path}\n")
    return best


def main():
    p = argparse.ArgumentParser(description="Optuna optimizer for binary strategy")
    p.add_argument("--trials", type=int, default=100)
    p.add_argument("--pair", default="BTC-USD")
    p.add_argument("--granularity", type=int, default=3600)
    p.add_argument("--bars", type=int, default=2000)
    args = p.parse_args()
    run(args.trials, args.pair, args.granularity, args.bars)


if __name__ == "__main__":
    main()
