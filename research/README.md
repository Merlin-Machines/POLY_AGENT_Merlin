# research/ — Silver-Fox tooling for the Merlin Polymarket agent

Offline backtesting, optimization, risk discipline, and ML training, ported from
the Silver-Fox crypto bot and **re-based onto binary Polymarket economics**. None
of this runs in the live loop — it's for tuning and model-building between sessions.

## What's here

| File | Purpose |
|------|---------|
| `candles.py` | Historical OHLCV loader — Kraken → Coinbase → synthetic fallback |
| `binary_market.py` | `BinaryPaperTrader` — YES/NO contract P&L (`shares * (exit - entry)`) |
| `risk_manager.py` | Fractional-Kelly sizing, ATR volatility scalar, drawdown / daily-loss / cooldown breakers |
| `backtest.py` | Walk-forward backtest through the full signal → ML → risk → execution gate chain |
| `optimizer.py` | Optuna search over signal + risk params (features precomputed once) |
| `train.py` | Trains `data/ml_filter.pkl` + `data/ml_scaler.pkl` for the **live** `utils.ml_filter.MLFilter` |

## Why "binary", not spot

Silver-Fox traded spot BTC (buy low / sell high). Merlin trades Polymarket binary
contracts: a YES share costs `p ∈ (0,1)` and pays `$1` if the outcome resolves true.
So every module here models P&L as:

```
cost     = shares * entry_price
proceeds = shares * exit_price      # exit_price ∈ {0,1} at resolution
pnl      = proceeds - cost = shares * (exit_price - entry_price)
```

A crypto BUY signal opens a YES contract on "price higher over the next H bars";
a SELL opens the inverse. Edge comes from the signal being right more often than
the entry price implies.

## ATR rule (carried from Chimera)

ATR is **never** used as a stop-loss/take-profit price on a Polymarket token — a
token price is not spot BTC. ATR only (a) scales position size down in turbulent
regimes and (b) vetoes entries above `atr_veto_pct`. See `risk_manager.size_position`.

## Usage

```bash
# Backtest on live Kraken data (falls back to synthetic offline)
python -m research.backtest --pair BTC-USD --horizon 6

# Train the ML filter the live bot will load automatically
python -m research.train --force-synthetic --bars 5000     # offline, lots of samples
python -m research.train --pair BTC-USD                    # live data when available

# Search for better parameters (writes research/best_params.json)
python -m research.optimizer --trials 100 --pair BTC-USD
```

After `train.py` writes `data/ml_filter.pkl`, the live agent's `MLFilter.load()`
finds it on next start — no further wiring needed. The feature contract
(`utils.indicators.FEATURE_COLS`) is shared end-to-end, so training and inference
always agree on column order.

## Dependencies

Core (`numpy`, `pandas`, `requests`) ship with the agent. For training/optimizing:

```bash
pip install xgboost scikit-learn joblib optuna
```

All three scripts degrade gracefully if optional deps are missing.
