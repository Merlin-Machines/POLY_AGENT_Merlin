"""
OrderbookRuntime — fast-tick event-driven loop for BTC markets near expiry.

Runs as a daemon thread alongside the main 45 s cycle scanner.
Wakes every `tick_interval` seconds (default 10 s) and calls registry.tick()
for each BTC market with < 600 s remaining.

Activated automatically when update_markets() finds near-expiry markets;
shuts itself down when none remain.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

log = logging.getLogger(__name__)

_NEAR_EXPIRY_SECONDS = 600   # activate when market has < 10 minutes left


class OrderbookRuntime:
    def __init__(
        self,
        registry,
        executor,
        fetch_spread_fn: Optional[Callable] = None,
        tick_interval: float = 10.0,
    ):
        self.registry = registry
        self.executor = executor
        self.fetch_spread_fn = fetch_spread_fn
        self.tick_interval = tick_interval

        self._active_markets: dict[str, dict] = {}   # market_id → market dict
        self._candle_analysis: dict = {}
        self._current_price: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._signal_count = 0
        self._exec_lock = threading.Lock()           # guard executor.execute()

    # ---------------------------------------------------------- context update
    def update_context(self, candle_analysis: dict, current_price: float):
        """Called from the main cycle to keep price/candle data fresh."""
        with self._lock:
            self._candle_analysis = dict(candle_analysis)
            self._current_price = float(current_price)

    def update_markets(self, btc_markets: list[dict]):
        """Refresh near-expiry market set; start/stop the fast loop accordingly."""
        near: dict[str, dict] = {}
        now = datetime.now(timezone.utc)
        for m in btc_markets:
            end_str = m.get("endDate") or m.get("end_date_iso")
            if not end_str:
                continue
            for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"]:
                try:
                    end = datetime.strptime(end_str, fmt).replace(tzinfo=timezone.utc)
                    secs = (end - now).total_seconds()
                    if 0 < secs <= _NEAR_EXPIRY_SECONDS:
                        near[m.get("id", "")] = m
                    break
                except Exception:
                    continue

        with self._lock:
            self._active_markets = near

        if near and not self._running:
            log.info(f"ORDERBOOK_RUNTIME | {len(near)} near-expiry market(s) — starting fast loop")
            self._start()
        elif not near and self._running:
            log.info("ORDERBOOK_RUNTIME | no near-expiry markets — stopping fast loop")
            self._running = False

    # ---------------------------------------------------------- thread control
    def _start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="poly_btc_ob")
        self._thread.start()

    def stop(self):
        self._running = False

    # ---------------------------------------------------------------- main loop
    def _loop(self):
        log.info(f"ORDERBOOK_RUNTIME | loop started (tick={self.tick_interval}s)")
        while self._running:
            try:
                self._tick_all()
            except Exception as exc:
                log.error(f"ORDERBOOK_RUNTIME | tick error: {exc}", exc_info=True)
            time.sleep(self.tick_interval)
        log.info("ORDERBOOK_RUNTIME | loop exited")

    def _tick_all(self):
        with self._lock:
            markets = dict(self._active_markets)
            candles = dict(self._candle_analysis)
            price = self._current_price

        if not markets:
            self._running = False
            return

        for market_id, market in list(markets.items()):
            opp = self.registry.tick(market, candles, price, self.fetch_spread_fn)
            if opp:
                self.registry.telemetry["totals"]["orderbook_signal_count"] += 1
                self._signal_count += 1
                self._submit(opp)

    # ------------------------------------------------------------ execution
    def _submit(self, opp):
        """Convert BTCOpportunity to executor-compatible object and submit."""
        std = self.registry._to_standard_opp(opp)
        try:
            class _FM:
                pass
            class _FO:
                pass
            fm = _FM()
            fm.market_id = std["market_id"]
            fm.question = std["question"]
            fm.symbol = std["sym"]
            fm.yes_price = std["yp"]
            fm.no_price = round(1.0 - float(std["yp"]), 4)
            fm.liquidity = 1000
            fm.hours_to_expiry = round(opp.seconds_to_expiry / 3600.0, 4)
            fm.yes_token_id = std["tid"]
            fm.no_token_id = ""
            fo = _FO()
            fo.market = fm
            fo.best_side = std["side"]
            fo.best_edge = std["edge"]
            fo.best_market_price = std["price"]
            fo.best_token_id = std["tid"]
            fo.trade_size = std["size"]
            fo.confidence = std["conf"]
            fo.our_prob_yes = std["op"]
            fo.market_prob_yes = std["yp"]

            log.info(
                f"ORDERBOOK_RUNTIME | {std['strategy']} | {std['side']} "
                f"${std['size']} edge={std['edge']:.1%} secs={opp.seconds_to_expiry:.0f}"
            )
            with self._exec_lock:
                rec = self.executor.execute(fo, manager_profile=None)
            log.info(f"ORDERBOOK_RUNTIME | result={rec.status}")
        except Exception as exc:
            log.error(f"ORDERBOOK_RUNTIME | submit failed: {exc}", exc_info=True)

    # ---------------------------------------------------------------- props
    @property
    def active_market_count(self) -> int:
        return len(self._active_markets)

    @property
    def signal_count(self) -> int:
        return self._signal_count

    @property
    def is_running(self) -> bool:
        return self._running
