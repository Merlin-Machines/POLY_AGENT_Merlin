"""
crypto_markets.py — dedicated BTC/ETH market sourcing for the crypto pack.

The default top-by-volume market pull surfaces almost no crypto markets (we were
seeing 1). Polymarket actually carries a rich recurring BTC/ETH universe — price
range markets, "reach $X" markets, and high-frequency "Up or Down" series — but
they only show up if you query several ways and merge:

  1. tag=crypto ordered by VOLUME   -> liquid price-range / reach markets
  2. tag=crypto ordered by END DATE -> soon-resolving crypto markets
  3. global ordered by END DATE      -> the "Bitcoin/Ethereum Up or Down" series
                                        (these are not always crypto-tagged)

Everything is deduped by conditionId and filtered to genuine BTC/ETH questions.
Pure read-only market discovery — no trading here.
"""
from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com/markets"
_BTC_ETH = re.compile(r"\b(btc|bitcoin|eth|ethereum)\b", re.IGNORECASE)

# Multiple sourcing passes. Each is a Gamma /markets query.
_QUERIES = [
    {"active": "true", "closed": "false", "limit": 200, "tag_slug": "crypto", "order": "volume", "ascending": "false"},
    {"active": "true", "closed": "false", "limit": 200, "tag_slug": "crypto", "order": "endDate", "ascending": "true"},
    {"active": "true", "closed": "false", "limit": 200, "order": "endDate", "ascending": "true"},
    {"active": "true", "closed": "false", "limit": 200, "order": "volume", "ascending": "false"},
]


def _is_btc_eth(question: str) -> bool:
    return bool(_BTC_ETH.search(question or ""))


def _market_key(m: dict) -> str:
    return str(m.get("conditionId") or m.get("condition_id") or m.get("id") or m.get("question", ""))


def fetch_crypto_markets(timeout: float = 12.0) -> list[dict]:
    """Return a deduped list of active BTC/ETH markets sourced across several queries."""
    seen: set[str] = set()
    out: list[dict] = []
    for params in _QUERIES:
        try:
            resp = requests.get(GAMMA_API, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
        except Exception as exc:
            log.debug("crypto_markets query failed (%s): %s", params.get("order"), exc)
            continue
        for m in items:
            if not _is_btc_eth(m.get("question", "")):
                continue
            key = _market_key(m)
            if key in seen:
                continue
            seen.add(key)
            out.append(m)
    log.info("crypto_markets | sourced %d unique BTC/ETH markets", len(out))
    return out


def merge_markets(base: list[dict], extra: list[dict]) -> list[dict]:
    """Merge two market lists, deduping by conditionId/id, preserving order (base first)."""
    seen: set[str] = set()
    merged: list[dict] = []
    for m in list(base) + list(extra):
        key = _market_key(m)
        if key in seen:
            continue
        seen.add(key)
        merged.append(m)
    return merged
