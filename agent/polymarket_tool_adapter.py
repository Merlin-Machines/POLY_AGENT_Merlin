import json
from typing import Any

import requests

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


class PolymarketToolAdapter:
    """Small safe subset inspired by Forbiddenkrostride/Polymarket-Tool."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "POLY_AGENT/1.0"})

    def get_markets(self, limit: int = 100, tag_slug: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"active": "true", "closed": "false", "limit": int(limit)}
        if tag_slug:
            params["tag_slug"] = tag_slug
        response = self._session.get(f"{GAMMA_API}/markets", params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def get_top_markets(self, limit: int = 100, tag_slugs: list[str] | None = None) -> list[dict[str, Any]]:
        tag_slugs = tag_slugs or ["weather", "crypto", "finance"]
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tag in tag_slugs:
            try:
                batch = self.get_markets(limit=limit, tag_slug=tag)
            except Exception:
                continue
            for market in batch:
                market_id = str(market.get("id", "") or "")
                if not market_id or market_id in seen:
                    continue
                seen.add(market_id)
                merged.append(market)
        merged.sort(
            key=lambda market: (
                float(market.get("volume24hr", 0) or 0),
                float(market.get("liquidity", 0) or 0),
            ),
            reverse=True,
        )
        return merged[:limit]

    def get_spread(self, token_id: str) -> dict[str, Any] | None:
        if not token_id:
            return None
        try:
            response = self._session.get(
                f"{CLOB_API}/spread",
                params={"token_id": token_id},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            best_bid = float(payload.get("bid", 0) or 0)
            best_ask = float(payload.get("ask", 0) or 0)
            spread = max(0.0, best_ask - best_bid) if best_bid and best_ask else float(payload.get("spread", 0) or 0)
            spread_pct = (spread / best_ask) if best_ask > 0 else 0.0
            return {
                "bid": best_bid,
                "ask": best_ask,
                "spread": spread,
                "spread_pct": spread_pct,
            }
        except Exception:
            return None

    def normalize_outcomes(self, market: dict[str, Any]) -> tuple[list[Any], list[Any], list[Any]]:
        outcomes = _as_list(market.get("outcomes", []))
        prices = _as_list(market.get("outcomePrices", []))
        token_ids = _as_list(market.get("clobTokenIds", []))
        return outcomes, prices, token_ids
