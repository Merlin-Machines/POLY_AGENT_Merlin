"""
CollapseSnipe strategy — 60-120 s before expiry.

Targets markets that are actively collapsing: a side that was trading at
0.25-0.35 and is now drifting toward 0.05-0.10.  The gap between market
price and expected resolution (0 or 1) provides a last-minute arbitrage.

Requires chaotic or tilting state (the collapse has started but isn't over).

SCORING: stub — returns None until wired.  Architecture and activation logic
are complete; add your edge model inside score() to enable the strategy.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.poly_btc.base import BTCOpportunity, BaseStrategy, StrategyConfig
from agent.poly_btc.state_classifier import MarketStateResult

log = logging.getLogger(__name__)

_ACTIVE_STATES = {"tilting", "chaotic"}


class CollapseSnipe(BaseStrategy):
    name = "collapse_snipe"

    def should_activate(self, market_state: str, seconds_to_expiry: float) -> bool:
        if not super().should_activate(market_state, seconds_to_expiry):
            return False
        return market_state in _ACTIVE_STATES

    def score(
        self,
        market: dict,
        btc_price: float,
        candle_analysis: dict,
        market_state_obj: MarketStateResult,
    ) -> Optional[BTCOpportunity]:
        # TODO: implement collapse snipe scoring
        #
        # Suggested approach:
        #   1. Confirm yes_price is in the "collapsing" band: 0.08-0.30 or 0.70-0.92
        #   2. Determine resolution direction from BTC price vs target:
        #        → If BTC >> target and yes_price still > 0.25, YES is overpriced → bet NO
        #        → If BTC << target and yes_price still < 0.75, NO is overpriced → bet YES
        #   3. Edge = | resolution_expectation - yes_price |
        #      where resolution_expectation ≈ 0.04 (NO) or 0.96 (YES) given BTC distance
        #   4. Only fire if edge ≥ min_edge (default 0.10) AND spread ≤ max_spread_pct
        #
        # This strategy is high-edge but fills poorly — FOK taker + strict spread gate.
        log.debug(f"COLLAPSE_SNIPE | score stub called for {market.get('id', '')[:8]}")
        return None
