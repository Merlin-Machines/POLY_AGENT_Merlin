from typing import Iterable
import json
import requests

from polymarket_v2.domain.models import Market


class PolymarketGammaProvider:
    def __init__(self, timeout_seconds: int = 12) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_markets(self) -> Iterable[Market]:
        raw_markets: list[dict] = []
        for tag in ("weather", "crypto", "finance"):
            response = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={"active": "true", "closed": "false", "limit": 100, "tag_slug": tag},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            raw_markets.extend(response.json())

        dedup: dict[str, dict] = {}
        for item in raw_markets:
            key = str(item.get("id", ""))
            if key and key not in dedup:
                dedup[key] = item

        markets: list[Market] = []
        for item in dedup.values():
            outcomes = item.get("outcomes") or []
            prices = item.get("outcomePrices") or []
            token_ids = item.get("clobTokenIds") or []
            if isinstance(token_ids, str):
                try:
                    token_ids = json.loads(token_ids)
                except json.JSONDecodeError:
                    token_ids = []
            if len(outcomes) < 2 or len(prices) < 2 or len(token_ids) < 2:
                continue
            try:
                yes_index = next(i for i, name in enumerate(outcomes) if name.lower() == "yes")
                no_index = next(i for i, name in enumerate(outcomes) if name.lower() == "no")
            except StopIteration:
                continue
            try:
                markets.append(
                    Market(
                        market_id=str(item.get("id", "")),
                        question=str(item.get("question", "")),
                        yes_price=float(prices[yes_index]),
                        no_price=float(prices[no_index]),
                        yes_token_id=str(token_ids[yes_index]),
                        no_token_id=str(token_ids[no_index]),
                        liquidity=float(item.get("liquidity") or 0.0),
                        hours_to_expiry=24.0,
                        symbol="POLY",
                    )
                )
            except (TypeError, ValueError):
                continue
        return markets
