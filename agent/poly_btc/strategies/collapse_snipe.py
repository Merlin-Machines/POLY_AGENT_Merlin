"""
CollapseSnipe — 60-120 s before expiry, tilting / chaotic / normal state.

Target: BTC has clearly resolved the question (gap > 2% from target) but the
market price hasn't fully repriced yet.  Classic: BTC at $94k, target $100k,
yes_price still at 0.30 with 90s remaining — that NO is nearly certain, yet
the market is leaving a 70-cent discount on the table.

Edge model:
  snipe_resolution_prob() gives near-certainty once gap > 2% + time < 120s.
  Only enters the LOSING side (the side that still has mispricing room).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from agent.poly_btc.base import BTCOpportunity, BaseStrategy, StrategyConfig
from agent.poly_btc.state_classifier import MarketStateResult
from agent.poly_btc.utils import as_list, parse_money_target, snipe_resolution_prob

log = logging.getLogger(__name__)

_ACTIVE_STATES = {"tilting", "chaotic", "normal", "flip_candidate"}


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

        target = parse_money_target(question)
        if not target or target <= 100 or btc_price <= 0:
            return None

        seconds_to_expiry = 90.0
        end_str = market.get("endDate") or market.get("end_date_iso")
        if end_str:
            for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"]:
                try:
                    end = datetime.strptime(end_str, fmt).replace(tzinfo=timezone.utc)
                    seconds_to_expiry = max(0.0, (end - datetime.now(timezone.utc)).total_seconds())
                    break
                except Exception:
                    continue

        prob_yes, abs_gap = snipe_resolution_prob(btc_price, target, seconds_to_expiry, candle_analysis)

        # collapse_snipe requires a CLEAR direction — gap must be ≥ 2%
        if abs_gap < 0.02:
            return None

        edge_yes = prob_yes - yes_price
        edge_no = (1.0 - prob_yes) - no_price
        if edge_yes >= edge_no:
            side, edge, price, tid = "YES", edge_yes, yes_price, tids[yi]
        else:
            side, edge, price, tid = "NO", edge_no, no_price, tids[ni]

        if edge < self.config.min_edge:
            return None

        # Only enter if there's still real mispricing — market price < max_entry_price
        if price > self.config.max_entry_price:
            return None

        size = round(min(self.config.max_size_usdc, max(0.5, 0.5 + edge * 15.0)), 2)
        conf = "HIGH" if edge >= 0.25 else "MEDIUM" if edge >= 0.15 else "LOW"

        log.info(
            f"COLLAPSE_SNIPE | {question[:55]} | {side} edge={edge:.1%} "
            f"gap={abs_gap:.1%} secs={seconds_to_expiry:.0f} state={market_state_obj.label}"
        )
        return BTCOpportunity(
            market_id=market_id, question=question, token_id=tid,
            side=side, strategy=self.name, edge=edge, price=price,
            our_prob=prob_yes if side == "YES" else 1.0 - prob_yes,
            size_usdc=size,
            order_type=self.config.entry_order_type, tif=self.config.entry_tif,
            market_state=market_state_obj.label,
            seconds_to_expiry=seconds_to_expiry, confidence=conf,
        )
