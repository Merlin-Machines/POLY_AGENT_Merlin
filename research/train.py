"""
research/train.py — train the XGBoost ML signal filter for the live agent.

Builds Silver-Fox features over real (or synthetic) candle history, labels each
EMA/RSI signal by whether a BINARY contract on its direction would have resolved
YES over a forward horizon, then trains an XGBoost classifier with a RobustScaler.

The output (data/ml_filter.pkl + data/ml_scaler.pkl) is written in exactly the
format utils.ml_filter.MLFilter expects, so the live bot picks it up with no code
changes — it scales a FEATURE_COLS row and reads predict_proba()[:,1].

Usage:
    python -m research.train
    python -m research.train --pair ETH-USD --bars 3000 --horizon 6
    python -m research.train --force-synthetic
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from utils.indicators import build_feature_snapshot, technical_signal, FEATURE_COLS
from research.candles import load_candles, _synthetic, trailing_window


def build_training_table(candles: list[dict], horizon: int, warmup: int = 60):
    """Return (X, y) over bars where a BUY/SELL signal fired."""
    closes = [c["close"] for c in candles]
    n = len(candles)
    rows, labels = [], []
    for i in range(warmup, n - horizon):
        feats = build_feature_snapshot(trailing_window(candles, i))
        sig, _ = technical_signal(feats)
        if sig not in ("BUY", "SELL"):
            continue
        moved_up = closes[i + horizon] > closes[i]
        won = moved_up if sig == "BUY" else (not moved_up)
        rows.append([float(feats.get(col, 0.0) or 0.0) for col in FEATURE_COLS])
        labels.append(int(won))
    return np.array(rows, dtype=float), np.array(labels, dtype=int)


def train(product_id="BTC-USD", granularity=3600, bars=3000, horizon=6,
          force_synthetic=False, out_dir="data", verbose=True):
    try:
        import joblib
        import xgboost as xgb
        from sklearn.preprocessing import RobustScaler
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import roc_auc_score
    except Exception as exc:
        raise SystemExit(
            f"Missing ML deps ({exc}). Install: pip install xgboost scikit-learn joblib"
        )

    if force_synthetic:
        candles = _synthetic(product_id, bars)
        src = "synthetic"
    else:
        candles = load_candles(product_id, granularity, bars)
        src = "live/kraken-coinbase or synthetic fallback"

    if verbose:
        print(f"\n{'='*56}\n  ML Signal Filter — Training ({product_id})\n{'='*56}")
        print(f"  Data source : {src}")
        print(f"  Candles     : {len(candles)}")
        print("  Building features + labels (expanding window)…")

    X, y = build_training_table(candles, horizon)
    if len(X) < 40:
        raise SystemExit(f"Too few signal samples to train: {len(X)} (need 40+).")

    scaler = RobustScaler()
    Xs = scaler.fit_transform(X)

    pos_rate = float(y.mean()) if len(y) else 0.5
    scale_pos = (1 - pos_rate) / (pos_rate + 1e-9)

    model = xgb.XGBClassifier(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=scale_pos, eval_metric="auc", random_state=42, verbosity=0,
    )

    aucs = []
    tscv = TimeSeriesSplit(n_splits=4)
    for tr, va in tscv.split(Xs):
        model.fit(Xs[tr], y[tr])
        if len(np.unique(y[va])) > 1:
            aucs.append(roc_auc_score(y[va], model.predict_proba(Xs[va])[:, 1]))
    model.fit(Xs, y)

    os.makedirs(out_dir, exist_ok=True)
    model_path = os.path.join(out_dir, "ml_filter.pkl")
    scaler_path = os.path.join(out_dir, "ml_scaler.pkl")
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)

    if verbose:
        print(f"  Samples     : {len(X)}  ({int(y.sum())} won / {int((1-y).sum())} lost)")
        print(f"  CV AUC      : {np.mean(aucs):.3f} ± {np.std(aucs):.3f}" if aucs else "  CV AUC      : n/a")
        imp = sorted(zip(FEATURE_COLS, model.feature_importances_), key=lambda x: -x[1])[:5]
        print("  Top features:")
        for f, v in imp:
            print(f"    {f:<18}: {v:.4f}")
        print(f"\n  Saved → {model_path}\n  Saved → {scaler_path}\n{'='*56}\n")

    return model_path, scaler_path


def main():
    p = argparse.ArgumentParser(description="Train ML signal filter")
    p.add_argument("--pair", default="BTC-USD")
    p.add_argument("--granularity", type=int, default=3600)
    p.add_argument("--bars", type=int, default=3000)
    p.add_argument("--horizon", type=int, default=6)
    p.add_argument("--force-synthetic", action="store_true")
    args = p.parse_args()
    train(args.pair, args.granularity, args.bars, args.horizon, args.force_synthetic)


if __name__ == "__main__":
    main()
