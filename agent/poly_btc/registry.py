"""
PolyBTCRegistry — central orchestrator for the poly_btc strategy pack.

Responsibilities:
  • Load / save per-strategy configs from data/poly_btc_config.json
  • Instantiate and own strategy objects
  • Run cycle scan (called from main.py each 45 s cycle)
  • Expose single-market tick() for orderbook_runtime fast loop
  • Persist and expose telemetry (attempts / fills / misses / pnl per strategy)
  • Host the OrderbookRuntime; wire executor after agent startup
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from agent.poly_btc.base import BTCOpportunity, StrategyConfig
from agent.poly_btc.fill_model import FillModel
from agent.poly_btc.state_classifier import MarketStateResult, classify
from agent.poly_btc.strategies.collapse_snipe import CollapseSnipe
from agent.poly_btc.strategies.conviction import Conviction
from agent.poly_btc.strategies.penny_flip import PennyFlip
from agent.poly_btc.strategies.resolution_snipe import ResolutionSnipe
from agent.poly_btc.utils import as_list

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ defaults

STRATEGY_CLASSES = {
    "conviction": Conviction,
    "penny_flip": PennyFlip,
    "collapse_snipe": CollapseSnipe,
    "resolution_snipe": ResolutionSnipe,
}

DEFAULT_CONFIGS: dict[str, dict] = {
    "conviction": {
        "enabled": True,
        "seconds_remaining_min": 3600.0,
        # 1 year: captures long-dated "before GTA VI" / "before 2026" BTC markets
        "seconds_remaining_max": 31_536_000.0,
        "entry_order_type": "FOK",
        "exit_order_type": "FOK",
        "entry_tif": "IOC",
        "exit_tif": "IOC",
        "stop_loss_pct": 0.08,
        "profit_take_pct": 0.12,
        "max_entry_price": 0.88,
        "max_spread_pct": 0.18,
        "max_size_usdc": 5.0,
        "cooldown_seconds": 300,
        "confirmation_ticks": 0,
        "allow_taker": True,
        "allow_limit": True,
        "min_edge": 0.05,
    },
    "penny_flip": {
        "enabled": True,
        "seconds_remaining_min": 60.0,
        "seconds_remaining_max": 180.0,
        "entry_order_type": "FOK",
        "exit_order_type": "FOK",
        "entry_tif": "IOC",
        "exit_tif": "IOC",
        "stop_loss_pct": 0.20,
        "profit_take_pct": 0.30,
        "max_entry_price": 0.60,
        "max_spread_pct": 0.25,
        "max_size_usdc": 2.0,
        "cooldown_seconds": 120,
        "confirmation_ticks": 1,
        "allow_taker": True,
        "allow_limit": False,
        "min_edge": 0.08,
    },
    "collapse_snipe": {
        "enabled": True,
        "seconds_remaining_min": 60.0,
        "seconds_remaining_max": 120.0,
        "entry_order_type": "FOK",
        "exit_order_type": "FOK",
        "entry_tif": "IOC",
        "exit_tif": "IOC",
        "stop_loss_pct": 0.25,
        "profit_take_pct": 0.40,
        "max_entry_price": 0.85,   # pay up to 85¢ for the resolving side
        "max_spread_pct": 0.30,
        "max_size_usdc": 1.5,
        "cooldown_seconds": 60,
        "confirmation_ticks": 1,
        "allow_taker": True,
        "allow_limit": False,
        "min_edge": 0.10,
    },
    "resolution_snipe": {
        "enabled": True,
        "seconds_remaining_min": 0.0,
        "seconds_remaining_max": 60.0,
        "entry_order_type": "FOK",
        "exit_order_type": "FOK",
        "entry_tif": "IOC",
        "exit_tif": "IOC",
        "stop_loss_pct": 0.50,
        "profit_take_pct": 0.50,
        "max_entry_price": 0.85,   # pay up to 85¢ for near-certain resolution
        "max_spread_pct": 0.40,
        "max_size_usdc": 1.0,
        "cooldown_seconds": 30,
        "confirmation_ticks": 0,
        "allow_taker": True,
        "allow_limit": False,
        "min_edge": 0.15,
    },
}

# Priority order for strategy evaluation within a market (most specific first)
_EVAL_ORDER = ["resolution_snipe", "collapse_snipe", "penny_flip", "conviction"]


def _empty_telemetry() -> dict:
    return {
        "strategies": {
            name: {"attempts": 0, "fills": 0, "misses": 0, "pnl": 0.0, "last_attempt_at": None}
            for name in STRATEGY_CLASSES
        },
        "totals": {
            "missed_fill_count": 0,
            "spread_reject_count": 0,
            "dead_liquidity_count": 0,
            "orderbook_signal_count": 0,
            "state_classifier_counts": {
                label: 0
                for label in ("resolved_like", "tilting", "chaotic",
                              "dead_liquidity", "flip_candidate", "normal")
            },
        },
        "last_updated": None,
    }


# ----------------------------------------------------------------- registry

class PolyBTCRegistry:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.fill_model = FillModel()
        self.config: dict[str, dict] = {}
        self.strategies: dict[str, object] = {}
        self.telemetry: dict = _empty_telemetry()
        self.orderbook_runtime = None       # set after executor is available
        self._load_config()
        self._load_telemetry()
        self._build_strategies()

    # ----------------------------------------------------------------- config

    @property
    def _config_path(self) -> Path:
        return self.data_dir / "poly_btc_config.json"

    @property
    def _telemetry_path(self) -> Path:
        return self.data_dir / "poly_btc_telemetry.json"

    def _load_config(self):
        if self._config_path.exists():
            try:
                saved = json.loads(self._config_path.read_text(encoding="utf-8"))
                for name, defaults in DEFAULT_CONFIGS.items():
                    merged = dict(defaults)
                    merged.update(saved.get(name, {}))
                    self.config[name] = merged
                return
            except Exception as exc:
                log.warning(f"poly_btc_config load error ({exc}); using defaults")
        self.config = {n: dict(c) for n, c in DEFAULT_CONFIGS.items()}
        self._save_config()

    def _save_config(self):
        try:
            self._config_path.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning(f"poly_btc_config save failed: {exc}")

    def _load_telemetry(self):
        if self._telemetry_path.exists():
            try:
                self.telemetry = json.loads(self._telemetry_path.read_text(encoding="utf-8"))
                return
            except Exception:
                pass
        self.telemetry = _empty_telemetry()

    def _save_telemetry(self):
        try:
            self.telemetry["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._telemetry_path.write_text(
                json.dumps(self.telemetry, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.debug(f"poly_btc telemetry save failed: {exc}")

    # --------------------------------------------------------------- strategies

    def _build_strategies(self):
        valid_fields = set(StrategyConfig.__dataclass_fields__.keys())
        for name, cls in STRATEGY_CLASSES.items():
            cfg_dict = self.config.get(name, DEFAULT_CONFIGS[name])
            filtered = {k: v for k, v in cfg_dict.items() if k in valid_fields}
            self.strategies[name] = cls(StrategyConfig(**filtered))

    def reload(self):
        """Reload config from disk and rebuild strategy instances."""
        self._load_config()
        self._build_strategies()
        log.info("POLY_BTC_REGISTRY | config reloaded")

    def patch_strategy_config(self, strategy_name: str, patch: dict) -> bool:
        if strategy_name not in self.config:
            return False
        self.config[strategy_name].update(patch)
        self._save_config()
        self.reload()
        return True

    # ---------------------------------------------------------------- executor

    def set_executor(self, executor):
        """
        Wire the TradeExecutor after agent startup so orderbook_runtime can
        submit orders.  Must be called before update_markets() fires.
        """
        from agent.poly_btc.orderbook_runtime import OrderbookRuntime
        self.orderbook_runtime = OrderbookRuntime(
            registry=self,
            executor=executor,
            tick_interval=10.0,
        )
        log.info("POLY_BTC_REGISTRY | OrderbookRuntime wired to executor")

    # ------------------------------------------------------------------- scan

    def scan(
        self,
        btc_markets: list[dict],
        candle_analysis: dict,
        current_price: float,
        get_spread_fn: Optional[Callable] = None,
    ) -> list[dict]:
        """
        Called each main cycle.  Returns standard opp dicts (same schema as
        agent/main.py analyze()) so the main executor loop handles them normally.
        """
        opps: list[BTCOpportunity] = []
        now = time.time()

        for market in btc_markets:
            opp = self._evaluate(market, candle_analysis, current_price, get_spread_fn, now)
            if opp:
                opps.append(opp)

        if opps:
            log.info(f"POLY_BTC_PACK | {len(opps)} opp(s) from {len(btc_markets)} BTC markets")
        self._save_telemetry()
        return [self._to_standard_opp(o) for o in opps]

    def tick(
        self,
        market: dict,
        candle_analysis: dict,
        current_price: float,
        get_spread_fn: Optional[Callable] = None,
    ) -> Optional[BTCOpportunity]:
        """Called by OrderbookRuntime each fast tick for a single near-expiry market."""
        opp = self._evaluate(market, candle_analysis, current_price, get_spread_fn, time.time())
        if opp:
            self._save_telemetry()
        return opp

    # ------------------------------------------------------------ core evaluator

    def _evaluate(
        self,
        market: dict,
        candle_analysis: dict,
        current_price: float,
        get_spread_fn: Optional[Callable],
        _now: float,
    ) -> Optional[BTCOpportunity]:
        outcomes = as_list(market.get("outcomes", []))
        oprices = as_list(market.get("outcomePrices", []))
        tids = as_list(market.get("clobTokenIds", []))
        if len(outcomes) < 2 or len(oprices) < 2 or len(tids) < 2:
            return None

        try:
            yi = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), 0)
            yes_price = float(oprices[yi])
        except Exception:
            return None

        # Seconds to expiry
        from datetime import timezone as tz
        seconds_to_expiry = 9_999_999.0
        end_str = market.get("endDate") or market.get("end_date_iso")
        if end_str:
            for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"]:
                try:
                    end = datetime.strptime(end_str, fmt).replace(tzinfo=tz.utc)
                    seconds_to_expiry = max(0.0, (end - datetime.now(tz.utc)).total_seconds())
                    break
                except Exception:
                    continue

        # Spread / liquidity
        spread_data = None
        if get_spread_fn:
            try:
                spread_data = get_spread_fn(tids[yi])
            except Exception:
                pass
        spread_pct = float((spread_data or {}).get("spread_pct", 0.0) or 0.0)
        liquidity = float(market.get("liquidity") or 0.0)

        # Classify market state
        state: MarketStateResult = classify(yes_price, spread_data, liquidity)
        label = state.label
        counts = self.telemetry["totals"]["state_classifier_counts"]
        counts[label] = counts.get(label, 0) + 1
        if label == "dead_liquidity":
            self.telemetry["totals"]["dead_liquidity_count"] += 1

        # resolved_like → nothing to trade
        if label == "resolved_like":
            return None

        market_id = market.get("id", "")

        # Try strategies in priority order (most time-constrained first)
        for name in _EVAL_ORDER:
            strategy = self.strategies.get(name)
            if not strategy:
                continue
            if not strategy.should_activate(label, seconds_to_expiry):
                continue
            if strategy.in_cooldown(market_id):
                continue

            tel = self.telemetry["strategies"][name]
            tel["attempts"] += 1
            tel["last_attempt_at"] = datetime.now(timezone.utc).isoformat()

            opp = strategy.score(market, current_price, candle_analysis, state)
            if opp is None:
                continue

            # Spread gate
            if spread_pct > strategy.config.max_spread_pct:
                self.telemetry["totals"]["spread_reject_count"] += 1
                log.debug(
                    f"POLY_BTC {name} | spread reject {spread_pct:.2%} "
                    f"> {strategy.config.max_spread_pct:.2%}"
                )
                continue

            # Fill-model gate (dry-run realism)
            fill = self.fill_model.simulate(
                order_type=strategy.config.entry_order_type,
                price=opp.price,
                size_usdc=opp.size_usdc,
                spread_pct=spread_pct,
                liquidity=liquidity,
            )
            if not fill.filled:
                tel["misses"] += 1
                self.telemetry["totals"]["missed_fill_count"] += 1
                log.debug(f"POLY_BTC {name} | fill miss: {fill.miss_reason}")
                continue

            tel["fills"] += 1
            strategy.record_entry(market_id)
            log.info(
                f"POLY_BTC {name} | {market.get('question','')[:50]} | {opp.side} "
                f"edge={opp.edge:.1%} state={label} secs={seconds_to_expiry:.0f}"
            )
            return opp

        return None

    # ------------------------------------------------------------------ helpers

    def record_pnl(self, strategy_name: str, pnl: float):
        """Update per-strategy P&L when a poly_btc-tagged position closes."""
        if strategy_name in self.telemetry["strategies"]:
            prev = self.telemetry["strategies"][strategy_name].get("pnl", 0.0)
            self.telemetry["strategies"][strategy_name]["pnl"] = round(prev + pnl, 6)
            self._save_telemetry()

    def _to_standard_opp(self, o: BTCOpportunity) -> dict:
        """Convert BTCOpportunity → standard opp dict (agent/main.py format)."""
        return {
            "market_id": o.market_id,
            "question": o.question,
            "sym": o.sym,
            "side": o.side,
            "edge": o.edge,
            "price": o.price,
            "tid": o.token_id,
            "size": o.size_usdc,
            "conf": o.confidence,
            "op": o.our_prob,
            "yp": o.price if o.side == "YES" else round(1.0 - o.price, 4),
            "strategy": f"BTC_PACK:{o.strategy}",
        }

    def get_telemetry(self) -> dict:
        return self.telemetry

    def get_config(self) -> dict:
        return self.config
