"""Crypto technical indicators adapted from Silver-Fox.

The runtime already fetches Binance candles as dictionaries with
open/high/low/close/volume keys.  This module keeps the feature pass dependency
light so the live bot can still start on a minimal install.
"""
from __future__ import annotations

import math
from typing import Iterable


FEATURE_COLS = [
    "ema9_21_spread",
    "ema21_50_spread",
    "price_ema50",
    "price_ema200",
    "macd_norm",
    "macd_hist",
    "rsi14",
    "rsi7",
    "rsi_diff",
    "atr_pct",
    "bb_width",
    "bb_pos",
    "hist_vol_10",
    "hist_vol_30",
    "vol_ratio",
    "dist_high20",
    "dist_low20",
    "body",
    "upper_wick",
    "lower_wick",
    "return_1",
    "return_3",
    "return_10",
]


def build_feature_snapshot(candles: Iterable[dict]) -> dict:
    """Return the latest Silver-Fox-style feature snapshot for OHLCV candles."""
    rows = [dict(c) for c in candles or []]
    if not rows:
        return _empty_features()

    opens = _series(rows, "open")
    highs = _series(rows, "high")
    lows = _series(rows, "low")
    closes = _series(rows, "close")
    volumes = _series(rows, "volume")
    close = closes[-1]

    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    macd_line = [fast - slow for fast, slow in zip(_ema(closes, 12), _ema(closes, 26))]
    macd_signal = _ema(macd_line, 9)
    atr14 = _atr(highs, lows, closes, 14)
    bb_mid, bb_upper, bb_lower = _bollinger(closes, 20, 2.0)
    high20 = max(highs[-20:]) if highs else close
    low20 = min(lows[-20:]) if lows else close

    prev_ema9 = ema9[-2] if len(ema9) > 1 else ema9[-1]
    prev_ema21 = ema21[-2] if len(ema21) > 1 else ema21[-1]
    rsi14_series = _rsi_series(closes, 14)
    rsi7_series = _rsi_series(closes, 7)
    avg_vol20 = _mean(volumes[-20:]) or 0.0
    body = abs(close - opens[-1]) / close if close else 0.0
    upper_wick = (highs[-1] - max(close, opens[-1])) / close if close else 0.0
    lower_wick = (min(close, opens[-1]) - lows[-1]) / close if close else 0.0

    features = {
        "ema9": ema9[-1],
        "ema21": ema21[-1],
        "ema50": ema50[-1],
        "ema200": ema200[-1],
        "prev_ema9": prev_ema9,
        "prev_ema21": prev_ema21,
        "ema9_21_spread": _ratio(ema9[-1] - ema21[-1], ema21[-1]),
        "ema21_50_spread": _ratio(ema21[-1] - ema50[-1], ema50[-1]),
        "price_ema50": _ratio(close - ema50[-1], ema50[-1]),
        "price_ema200": _ratio(close - ema200[-1], ema200[-1]),
        "macd": macd_line[-1] if macd_line else 0.0,
        "macd_signal": macd_signal[-1] if macd_signal else 0.0,
        "macd_hist": (macd_line[-1] - macd_signal[-1]) if macd_line and macd_signal else 0.0,
        "macd_norm": _ratio(macd_line[-1] if macd_line else 0.0, close),
        "rsi14": rsi14_series[-1],
        "rsi7": rsi7_series[-1],
        "rsi_diff": rsi14_series[-1] - (rsi14_series[-4] if len(rsi14_series) > 3 else rsi14_series[0]),
        "atr": atr14,
        "atr_pct": _ratio(atr14, close) * 100,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "bb_width": _ratio(bb_upper - bb_lower, bb_mid),
        "bb_pos": _ratio(close - bb_lower, (bb_upper - bb_lower) or 1e-9),
        "hist_vol_10": _hist_vol(closes, 10),
        "hist_vol_30": _hist_vol(closes, 30),
        "vol_ratio": _ratio(volumes[-1], avg_vol20) if avg_vol20 else 0.0,
        "dist_high20": _ratio(high20 - close, close),
        "dist_low20": _ratio(close - low20, close),
        "body": body,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "return_1": _return(closes, 1),
        "return_3": _return(closes, 3),
        "return_10": _return(closes, 10),
        "close": close,
    }
    return {key: _finite(value) for key, value in features.items()}


def technical_signal(features: dict, rsi_overbought: float = 72.0, rsi_oversold: float = 20.0) -> tuple[str, dict]:
    """Return BUY/SELL/HOLD plus human-readable reason from latest features."""
    ema9 = float(features.get("ema9", 0.0) or 0.0)
    ema21 = float(features.get("ema21", 0.0) or 0.0)
    prev_ema9 = float(features.get("prev_ema9", ema9) or ema9)
    prev_ema21 = float(features.get("prev_ema21", ema21) or ema21)
    rsi = float(features.get("rsi14", 50.0) or 50.0)

    crossed_up = ema9 > ema21 and prev_ema9 <= prev_ema21
    crossed_down = ema9 < ema21 and prev_ema9 >= prev_ema21
    details = {
        "ema_fast": round(ema9, 4),
        "ema_slow": round(ema21, 4),
        "rsi": round(rsi, 2),
        "ema_spread": round(ema9 - ema21, 4),
    }
    if crossed_up and rsi < rsi_overbought:
        details["reason"] = f"Silver-Fox EMA crossover up with RSI {rsi:.1f}"
        return "BUY", details
    if crossed_down and rsi > rsi_oversold:
        details["reason"] = f"Silver-Fox EMA crossover down with RSI {rsi:.1f}"
        return "SELL", details
    details["reason"] = "Silver-Fox hold: no confirmed EMA/RSI crossover"
    return "HOLD", details


def _empty_features() -> dict:
    return {key: 0.0 for key in FEATURE_COLS}


def _series(rows: list[dict], key: str) -> list[float]:
    return [float(row.get(key) or 0.0) for row in rows]


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return [0.0]
    multiplier = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append((value - out[-1]) * multiplier + out[-1])
    return out


def _rsi_series(values: list[float], period: int) -> list[float]:
    if len(values) < 2:
        return [50.0]
    rsis = [50.0]
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, len(values)):
        delta = values[idx] - values[idx - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
        window_gains = gains[-period:]
        window_losses = losses[-period:]
        avg_gain = _mean(window_gains)
        avg_loss = _mean(window_losses)
        if avg_loss == 0:
            rsis.append(100.0 if avg_gain > 0 else 50.0)
        else:
            rs = avg_gain / avg_loss
            rsis.append(100 - (100 / (1 + rs)))
    return rsis


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float:
    if len(closes) < 2:
        return 0.0
    trs = []
    for idx in range(1, len(closes)):
        trs.append(max(
            highs[idx] - lows[idx],
            abs(highs[idx] - closes[idx - 1]),
            abs(lows[idx] - closes[idx - 1]),
        ))
    return _mean(trs[-period:])


def _bollinger(values: list[float], period: int, std_mult: float) -> tuple[float, float, float]:
    window = values[-period:] if len(values) >= period else values
    mid = _mean(window)
    variance = _mean([(value - mid) ** 2 for value in window]) if window else 0.0
    std = math.sqrt(variance)
    return mid, mid + std_mult * std, mid - std_mult * std


def _hist_vol(values: list[float], period: int) -> float:
    returns = [_return(values[:idx + 1], 1) for idx in range(1, len(values))]
    window = returns[-period:]
    if len(window) < 2:
        return 0.0
    mid = _mean(window)
    return math.sqrt(_mean([(value - mid) ** 2 for value in window])) * 100


def _return(values: list[float], periods: int) -> float:
    if len(values) <= periods or values[-periods - 1] == 0:
        return 0.0
    return (values[-1] - values[-periods - 1]) / values[-periods - 1]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _finite(value: float) -> float:
    try:
        value = float(value)
    except Exception:
        return 0.0
    return value if math.isfinite(value) else 0.0
