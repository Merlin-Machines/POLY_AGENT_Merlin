from typing import Iterable

from polymarket_v2.domain.models import Market, Opportunity, Side
from polymarket_v2.strategies.base import Strategy


class WeatherRangesStrategy(Strategy):
    strategy_id = "weather_ranges_v1"

    def __init__(self, edge_threshold: float, max_trade_usd: float) -> None:
        self.edge_threshold = edge_threshold
        self.max_trade_usd = max_trade_usd

    def find_opportunities(self, markets: Iterable[Market]) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for market in markets:
            if "temperature" not in market.question.lower():
                continue
            if market.liquidity < 200:
                continue

            # Placeholder probability model for initial scaffold.
            modeled_yes_prob = 0.55
            edge_yes = modeled_yes_prob - market.yes_price
            edge_no = (1.0 - modeled_yes_prob) - market.no_price

            if edge_yes >= edge_no:
                side = Side.YES
                edge = edge_yes
                token_id = market.yes_token_id
                market_price = market.yes_price
            else:
                side = Side.NO
                edge = edge_no
                token_id = market.no_token_id
                market_price = market.no_price

            if edge < self.edge_threshold:
                continue

            size = min(self.max_trade_usd, max(1.0, edge * 100))
            opportunities.append(
                Opportunity(
                    market_id=market.market_id,
                    side=side,
                    edge=edge,
                    market_price=market_price,
                    token_id=token_id,
                    size_usd=round(size, 2),
                    strategy_id=self.strategy_id,
                    confidence="MEDIUM" if edge >= 0.05 else "LOW",
                    reason="Scaffold weather range signal",
                )
            )

        opportunities.sort(key=lambda item: item.edge, reverse=True)
        return opportunities
