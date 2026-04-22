import math
import re
from typing import Iterable

from polymarket_v2.connectors.price_feeds import normal_cdf
from polymarket_v2.connectors.weather_feed import calc_range_prob, detect_city, get_weather, parse_temp_range
from polymarket_v2.domain.models import Market, Opportunity, Side
from polymarket_v2.strategies.base import Strategy


class LegacyHybridStrategy(Strategy):
    strategy_id = "legacy_hybrid_v1"

    def __init__(self, edge_threshold: float, max_trade_usd: float) -> None:
        self.edge_threshold = edge_threshold
        self.max_trade_usd = max_trade_usd
        self.weather_cache: dict[str, dict] = {}

    def find_opportunities(
        self,
        markets: Iterable[Market],
        prices: dict[str, float],
        candle_analysis: dict[str, dict],
    ) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for market in markets:
            if market.liquidity < 200:
                continue
            if not (0.01 <= market.yes_price <= 0.99):
                continue

            our_prob = self._estimate_probability(market, prices, candle_analysis)
            if our_prob is None:
                continue

            edge_yes = our_prob - market.yes_price
            edge_no = (1.0 - our_prob) - market.no_price
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

            size = round(max(1.0, min(self.max_trade_usd, edge * 200)), 2)
            opportunities.append(
                Opportunity(
                    market_id=market.market_id,
                    side=side,
                    edge=edge,
                    market_price=market_price,
                    token_id=token_id,
                    size_usd=size,
                    strategy_id=self.strategy_id,
                    confidence=self._confidence(edge),
                    reason=f"Hybrid legacy signal on: {market.question[:80]}",
                )
            )

        opportunities.sort(key=lambda item: item.edge, reverse=True)
        return opportunities

    def _estimate_probability(
        self,
        market: Market,
        prices: dict[str, float],
        candle_analysis: dict[str, dict],
    ) -> float | None:
        question = market.question.lower()
        weather_words = ("temperature", "degrees", "high of", "low of", "warmer", "cooler", "temp", "weather")
        if any(word in question for word in weather_words):
            return self._weather_probability(market.question, market.yes_price)

        if any(word in question for word in ("btc", "bitcoin", "eth", "ethereum", "btc price", "eth price")):
            return self._crypto_probability(market.question, prices, candle_analysis)

        return None

    def _weather_probability(self, question: str, yes_price: float) -> float | None:
        city = detect_city(question)
        if not city:
            return None
        if city not in self.weather_cache:
            weather = get_weather(city)
            if weather:
                self.weather_cache[city] = weather
        weather = self.weather_cache.get(city)
        if not weather:
            return None
        temperature = weather.get("temp_f_today") or weather.get("temp_f")
        if not temperature:
            return None
        temp_range = parse_temp_range(question)
        if not temp_range:
            return None
        prob = calc_range_prob(float(temperature), temp_range)
        if yes_price < 0.10 and prob > 0.85:
            prob = min(0.95, prob + 0.08)
        return prob

    def _crypto_probability(self, question: str, prices: dict[str, float], candle_analysis: dict[str, dict]) -> float | None:
        symbol = "BTC" if ("btc" in question or "bitcoin" in question) else "ETH"
        price = prices.get(symbol)
        candles = candle_analysis.get(symbol)
        if not price or not candles:
            return None

        rsi = candles["rsi"]
        momentum = candles["momentum"]
        direction = None
        if rsi < 45:
            direction = "above"
        elif rsi > 55:
            direction = "below"
        elif abs(momentum) > 0.3:
            direction = "above" if momentum > 0 else "below"
        if not direction:
            return None

        strike_match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", question)
        if not strike_match:
            return None
        strike = float(strike_match.group(1).replace(",", ""))
        if strike <= 0:
            return None

        annual_vol = {"BTC": 0.65, "ETH": 0.80}.get(symbol, 0.70)
        t_years = max(24.0 / 8760, 1 / 8760)
        d2 = math.log(price / strike) / (annual_vol * math.sqrt(t_years))
        prob = normal_cdf(d2) if direction == "above" else 1 - normal_cdf(d2)
        prob = max(0.05, min(0.95, prob))
        if rsi < 45 or rsi > 55:
            prob = min(0.99, prob + 0.12)
        if abs(momentum) > 0.3:
            prob = min(0.99, prob + 0.08)
        return prob

    def _confidence(self, edge: float) -> str:
        if edge >= 0.10:
            return "HIGH"
        if edge >= 0.05:
            return "MEDIUM"
        return "LOW"
