"""
PennyFlip strategy — 60-180 s before expiry.

Fires on flip_candidate markets (price near 0.5) where a small move before
resolution means one side becomes a near-free bet.  Needs fast fill (FOK taker)
and a larger edge threshold to offset the timing risk.

SCORING: stub — returns None until wired.  Architecture and activation logic
are complete; add your edge model inside score() to enable the strategy.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.poly_btc.base import BTCOpportunity, BaseStrategy, StrategyConfig
from agent.poly_btc.state_classifier import MarketStateResult

log = logging.getLogger(__name__)

_ACTIVE_STATES = {"flip_candidate", "normal"}


class PennyFlip(BaseStrategy):
    name = "penny_flip"

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
        # TODO: implement near-expiry flip scoring
        #
        # Suggested approach:
        #   1. Confirm market is in the 60-180s window (already gated by should_activate)
        #   2. Compute real-time BTC distance from question target:
        #        gap_pct = abs(btc_price - target) / target
        #   3. If gap_pct < 0.005 (within 0.5% of target) → high probability of near-miss flip
        #   4. Decide side based on which direction BTC is moving (use candle momentum)
        #   5. Only enter if spread is tight enough (≤ max_spread_pct from config)
        #
        # Key difference from Conviction: uses seconds (not hours) and only fires
        # when the market is genuinely undecided at the moment of entry.
        log.debug(f"PENNY_FLIP | score stub called for {market.get('id', '')[:8]}")
        return None
