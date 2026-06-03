"""
research/candles.py — historical OHLCV loader for backtests and training.

Priority:
  1. Kraken public OHLC API (real BTC/ETH history, no auth)
  2. Coinbase public candles (no auth)
  3. Synthetic multi-regime GBM fallback (always works offline)

Returns plain list[dict] candles with open/high/low/close/volume keys so the
output feeds straight into utils.indicators.build_feature_snapshot.
"""
from __future__ import annotations

import math
import random
import time
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


KRAKEN_PAIR = {"BTC-USD": "XBTUSD", "ETH-USD": "ETHUSD", "SOL-USD": "SOLUSD"}
KRAKEN_INTERVAL = {300: 5, 900: 15, 3600: 60}  # seconds → Kraken minutes

# Longest indicator is EMA200; a trailing window of this many bars yields features
# statistically identical to the full expanding history while keeping per-bar
# feature construction O(W) instead of O(N). Without this, walk-forward loops are
# O(N^2) and choke on a few thousand bars.
FEATURE_LOOKBACK = 260


def trailing_window(candles: list[dict], i: int, lookback: int = FEATURE_LOOKBACK) -> list[dict]:
    """Return candles[..i] capped to the last `lookback` bars (inclusive of i)."""
    return candles[max(0, i + 1 - lookback): i + 1]


def load_candles(
    product_id: str = "BTC-USD",
    granularity: int = 3600,
    bars: int = 2000,
) -> list[dict]:
    """Load OHLCV candles as a list of dicts (oldest → newest).

    Source priority (real data first):
      1. CryptoCompare histo (up to ~2000 bars, no auth) — best for training depth
      2. Kraken public OHLC (~720 bars)
      3. Coinbase public candles (~300 bars)
      4. Synthetic GBM fallback
    """
    candles = _from_cryptocompare(product_id, granularity, bars)
    if candles and len(candles) >= 200:
        return candles[-bars:]

    candles = _from_kraken(product_id, granularity)
    if candles and len(candles) >= 50:
        return candles[-bars:]

    candles = _from_coinbase(product_id, granularity)
    if candles and len(candles) >= 50:
        return candles[-bars:]

    return _synthetic(product_id, bars)


def _from_cryptocompare(product_id: str, granularity: int, bars: int) -> Optional[list[dict]]:
    """CryptoCompare histohour/histoday/histominute — real OHLCV, no auth, up to 2000/call."""
    if requests is None:
        return None
    fsym = product_id.split("-")[0].upper()
    tsym = (product_id.split("-")[1] if "-" in product_id else "USD").upper()
    endpoint = {300: "histominute", 900: "histominute", 3600: "histohour", 86400: "histoday"}.get(
        granularity, "histohour"
    )
    aggregate = {300: 5, 900: 15}.get(granularity, 1)
    try:
        resp = requests.get(
            f"https://min-api.cryptocompare.com/data/v2/{endpoint}",
            params={"fsym": fsym, "tsym": tsym, "limit": min(bars, 2000), "aggregate": aggregate},
            timeout=12,
        )
        data = resp.json()
        if data.get("Response") != "Success":
            return None
        rows = data.get("Data", {}).get("Data", [])
        out = []
        for r in rows:
            if not r.get("close"):
                continue
            out.append({
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volumefrom", 0.0)),
            })
        return out or None
    except Exception:
        return None


def _from_kraken(product_id: str, granularity: int) -> Optional[list[dict]]:
    if requests is None:
        return None
    pair = KRAKEN_PAIR.get(product_id)
    interval = KRAKEN_INTERVAL.get(granularity, 60)
    if not pair:
        return None
    try:
        resp = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval},
            timeout=12,
        )
        data = resp.json()
        if data.get("error"):
            return None
        result = data.get("result", {})
        series = next((v for k, v in result.items() if k != "last"), [])
        out = []
        for row in series:
            # [time, open, high, low, close, vwap, volume, count]
            out.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[6]),
            })
        return out or None
    except Exception:
        return None


def _from_coinbase(product_id: str, granularity: int) -> Optional[list[dict]]:
    if requests is None:
        return None
    try:
        resp = requests.get(
            f"https://api.exchange.coinbase.com/products/{product_id}/candles",
            params={"granularity": granularity},
            headers={"User-Agent": "MerlinResearch/1.0"},
            timeout=12,
        )
        rows = resp.json()
        if not isinstance(rows, list):
            return None
        # Coinbase: [time, low, high, open, close, volume], newest first
        out = []
        for row in sorted(rows, key=lambda r: r[0]):
            out.append({
                "time": int(row[0]),
                "open": float(row[3]),
                "high": float(row[2]),
                "low": float(row[1]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
        return out or None
    except Exception:
        return None


def _synthetic(product_id: str, bars: int) -> list[dict]:
    """Multi-regime GBM synthetic series — deterministic per product."""
    base = {"BTC-USD": 67000.0, "ETH-USD": 3500.0, "SOL-USD": 180.0}.get(product_id, 1000.0)
    rng = random.Random(hash(product_id) & 0xFFFF)
    price = base
    out = []
    now = int(time.time()) - bars * 3600
    # alternate bull/bear/flat regimes every ~200 bars
    for i in range(bars):
        regime = (i // 200) % 3
        mu = {0: 0.0006, 1: -0.0006, 2: 0.0}[regime]
        sigma = {0: 0.010, 1: 0.013, 2: 0.006}[regime]
        ret = rng.gauss(mu, sigma)
        open_ = price
        close = price * math.exp(ret)
        high = max(open_, close) * (1 + abs(rng.gauss(0, sigma / 2)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, sigma / 2)))
        out.append({
            "time": now + i * 3600,
            "open": open_, "high": high, "low": low, "close": close,
            "volume": rng.uniform(100, 5000),
        })
        price = close
    return out
