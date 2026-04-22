import math
import requests


def get_spot_price(symbol: str) -> float | None:
    for url, key in (
        (f"https://min-api.cryptocompare.com/data/price?fsym={symbol}&tsyms=USD", "USD"),
        (f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot", "data"),
    ):
        try:
            payload = requests.get(url, timeout=8).json()
            if key == "USD":
                price = float(payload["USD"])
            else:
                price = float(payload["data"]["amount"])
            if price > 0:
                return price
        except Exception:
            continue
    return None


def get_5m_candles(symbol: str) -> list[dict] | None:
    try:
        response = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": f"{symbol}USDT", "interval": "5m", "limit": 20},
            timeout=8,
        )
        if response.status_code != 200:
            return None
        rows = response.json()
        return [
            {
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[7]),
            }
            for row in rows
        ]
    except Exception:
        return None


def analyze_candles(candles: list[dict] | None) -> dict:
    if not candles or len(candles) < 5:
        return {"rsi": 50.0, "momentum": 0.0, "trend": "neutral"}

    closes = [item["close"] for item in candles]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [value if value > 0 else 0 for value in deltas]
    losses = [-value if value < 0 else 0 for value in deltas]

    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else (sum(gains) / len(gains) if gains else 0)
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else (sum(losses) / len(losses) if losses else 0)
    rs = avg_gain / avg_loss if avg_loss > 0 else 0
    rsi = 100 - (100 / (1 + rs)) if rs > 0 else 50

    momentum = ((closes[-1] - closes[-5]) / closes[-5] * 100) if closes[-5] > 0 else 0
    short_ma = sum(closes[-5:]) / 5
    long_ma = sum(closes[-15:]) / 15 if len(closes) >= 15 else short_ma
    trend = "up" if short_ma > long_ma else ("down" if short_ma < long_ma else "neutral")

    return {"rsi": round(rsi, 1), "momentum": round(momentum, 2), "trend": trend}


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
