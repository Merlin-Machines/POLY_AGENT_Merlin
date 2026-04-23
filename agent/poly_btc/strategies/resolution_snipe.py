"""
ResolutionSnipe strategy — final 60 s only.

Attempts to buy the resolving side at a discount in the last seconds before
the CLOB closes.  Requires BTC price to clearly confirm the resolution
direction (distance from target > 1%) AND the market price to still have
mispricing (yes_price < 0.85 when BTC is clearly above target, or > 0.15
when clearly below).

Highest edge potential, lowest fill rate.  FOK only, no limit orders.

SCORING: stub — returns None until wired.  Architecture and activation logic
are complete; add your edge model inside score() to enable the strategy.
"""
from __future__ import annotations

import logging
from typing import Optional

from agent.poly_btc.base import BTCOpportunity, BaseStrategy, StrategyConfig
from agent.poly_btc.state_classifier import MarketStateResult

log = logging.getLogger(__name__)

# Only fire when BTC has clearly resolved the outcome — not for chaotic / dead markets
_ACTIVE_STATES = {"tilting", "normal", "flip_candidate"}


class ResolutionSnipe(BaseStrategy):
    name = "resolution_snipe"

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
        # TODO: implement resolution snipe scoring
        #
        # Suggested approach:
        #   1. Parse target from question
        #   2. Compute BTC distance: gap_pct = (btc_price - target) / target
        #   3. Strong YES signal:  gap_pct > +0.01 (BTC clearly above target)
        #      Strong NO  signal:  gap_pct < -0.01 (BTC clearly below target)
        #   4. Check market mispricing:
        #        YES signal + yes_price < 0.85  →  edge = 0.97 - yes_price
        #        NO  signal + no_price  < 0.85  →  edge = 0.97 - no_price
        #   5. Only fire if edge ≥ min_edge (default 0.15) — this is a certainty bet
        #   6. Size: always max_size_usdc (1.0) — tiny position, near-certain outcome
        #
        # Key risk: FOK fill rate in the final 60s can be very low; the fill_model
        # gate in registry.py will reject most of these in dry-run mode.
        log.debug(f"RESOLUTION_SNIPE | score stub called for {market.get('id', '')[:8]}")
        return None
