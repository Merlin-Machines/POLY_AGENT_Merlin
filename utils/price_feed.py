import time, logging, requests
log = logging.getLogger(__name__)
_cache = {}

def get_price(symbol):
    symbol = symbol.upper()
    if symbol in _cache:
        price, ts = _cache[symbol]
        if time.time() - ts < 15: return price
    for url, key in [
        (f"https://min-api.cryptocompare.com/data/price?fsym={symbol}&tsyms=USD", "USD"),
        (f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot", None),
        (f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT", None),
    ]:
        try:
            d = requests.get(url, timeout=8).json()
            if key:
                price = float(d[key])
            elif "data" in d:
                price = float(d["data"]["amount"])
            else:
                price = float(d["price"])
            if price > 0:
                _cache[symbol] = (price, time.time())
                log.info(f"{symbol}: \${price:,.2f}")
                return price
        except Exception as e:
            log.debug(f"Source failed: {e}")
    log.error(f"All price sources failed for {symbol}")
    return None

def get_prices_bulk():
    return {s: p for s in ["BTC","ETH"] if (p := get_price(s))}

