"""
Conviction strategy — long-horizon BTC position.

Fires when:
  • 1h–48h remaining in market (not last-minute, not expired)
  • Market state not resolved_like or dead_liquidity
  • Black-Scholes + candle signal boost produces edge ≥ min_edge (default 5%)
  • Price has not already resolved (yes_price < max_entry_price)

Edge model:
  Base probability via Black-Scholes d2 term (BTC vol = 65% annualised).
  Each aligned 5m candle signal (RSI, MACD, trend, Bollinger, momentum) adds
  a small boost (1.5–2%) in the predicted direction.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.poly_btc.base import BTCOpportunity, BaseStrategy, StrategyConfig
from agent.poly_btc.state_classifier import MarketStateResult
from agent.poly_btc.utils import as_list, black_scholes_prob, parse_money_target

log = logging.getLogger(__name__)

_BLOCKED_STATES = {"resolved_like", "dead_liquidity"}


class Conviction(BaseStrategy):
    name = "conviction"

    def should_activate(self, market_state: str, seconds_to_expiry: float) -> bool:
        if not super().should_activate(market_state, seconds_to_expiry):
            return False
        return market_state not in _BLOCKED_STATES

    def score(
        self,
        market: dict,
        btc_price: float,
        candle_analysis: dict,
        market_state_obj: MarketStateResult,
    ) -> Optional[BTCOpportunity]:
        question = market.get("question", "")
        market_id = market.get("id", "")

        outcomes = as_list(market.get("outcomes", []))
        oprices = as_list(market.get("outcomePrices", []))
        tids = as_list(market.get("clobTokenIds", []))
        if len(outcomes) < 2 or len(oprices) < 2 or len(tids) < 2:
            return None

        try:
            yi = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), 0)
            ni = next((i for i, o in enumerate(outcomes) if str(o).lower() == "no"), 1)
            yes_price = float(oprices[yi])
            no_price = float(oprices[ni])
        except Exception:
            return None

        # Don't enter if the market has already mostly resolved
        if yes_price > self.config.max_entry_price or yes_price < (1.0 - self.config.max_entry_price):
            return None

        # Parse the BTC price target embedded in the question
        target = parse_money_target(question)
        if not target or target <= 100 or btc_price <= 0:
            return None

        # Time to expiry
        from datetime import datetime, timezone
        seconds_to_expiry = 172800.0
        end_str = market.get("endDate") or market.get("end_date_iso")
        if end_str:
            for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"]:
                try:
                    end = datetime.strptime(end_str, fmt).replace(tzinfo=timezone.utc)
                    seconds_to_expiry = max(1.0, (end - datetime.now(timezone.utc)).total_seconds())
                    break
                except Exception:
                    continue

        T_years = max(seconds_to_expiry / 31_536_000.0, 1.0 / 8760.0)
        direction_above = target >= btc_price    # "will BTC hit $X" → target above price

        base_prob = black_scholes_prob(btc_price, target, T_years, vol=0.65,
                                       direction_above=direction_above)

        # Candle signal boost
        rsi = candle_analysis.get("rsi", 50)
        momentum = candle_analysis.get("momentum", 0.0)
        trend = candle_analysis.get("trend", "neutral")
        macd_hist = candle_analysis.get("macd_hist", 0.0)
        bollinger_signal = candle_analysis.get("bollinger_signal", "neutral")
        signal_boost = 0.0

        if direction_above:
            if rsi <= 45:          signal_boost += 0.020
            if macd_hist > 0:      signal_boost += 0.015
            if trend == "up":      signal_boost += 0.020
            if bollinger_signal == "bullish": signal_boost += 0.010
            if momentum > 0.25:    signal_boost += 0.015
        else:
            if rsi >= 55:          signal_boost += 0.020
            if macd_hist < 0:      signal_boost += 0.015
            if trend == "down":    signal_boost += 0.020
            if bollinger_signal == "bearish": signal_boost += 0.010
            if momentum < -0.25:   signal_boost += 0.015

        our_prob = max(0.05, min(0.95, base_prob + signal_boost))

        # Edge calculation — take the side with the larger edge
        edge_yes = our_prob - yes_price
        edge_no = (1.0 - our_prob) - no_price
        if edge_yes >= edge_no:
            side, edge, price, tid = "YES", edge_yes, yes_price, tids[yi]
        else:
            side, edge, price, tid = "NO", edge_no, no_price, tids[ni]

        if edge < self.config.min_edge:
            return None

        # Size scales linearly with edge up to max_size_usdc
        size = round(min(self.config.max_size_usdc, max(1.0, 1.0 + edge * 40.0)), 2)
        conf = "HIGH" if edge >= 0.12 else "MEDIUM" if edge >= 0.07 else "LOW"

        log.info(
            f"CONVICTION | {question[:55]} | {side} edge={edge:.1%} "
            f"prob={our_prob:.2f} vs mkt={price:.2f} state={market_state_obj.label}"
        )
        return BTCOpportunity(
            market_id=market_id,
            question=question,
            token_id=tid,
            side=side,
            strategy=self.name,
            edge=edge,
            price=price,
            our_prob=our_prob,
            size_usdc=size,
            order_type=self.config.entry_order_type,
            tif=self.config.entry_tif,
            market_state=market_state_obj.label,
            seconds_to_expiry=seconds_to_expiry,
            confidence=conf,
        )
