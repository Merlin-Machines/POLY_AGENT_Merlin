import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class Position:
    market_id: str
    question: str
    side: str
    entry_price: float
    size_usdc: float
    token_id: str
    symbol: str
    edge_at_entry: float
    opened_at: str
    status: str = "open"
    shares: float = 0.0
    dca_count: int = 0
    last_price: float = 0.0


@dataclass
class TradeRecord:
    timestamp: str
    market_id: str
    question: str
    side: str
    price: float
    size_usdc: float
    edge: float
    confidence: str
    status: str
    symbol: str
    our_prob: float
    market_prob: float
    error: Optional[str] = None
    order_id: Optional[str] = None
    shares: float = 0.0
    order_action: str = "entry"


class TradeExecutor:
    def __init__(self, config):
        self.cfg = config
        self.dry_run = not bool(config.private_key)
        self.positions = {}
        self.trade_history = []
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._today = date.today()
        self.client = None
        Path(config.log_dir).mkdir(exist_ok=True)
        Path(config.data_dir).mkdir(exist_ok=True)
        self._load_state()
        if self.dry_run:
            log.warning("DRY RUN - no private key")
        else:
            self._init_client()

    def _init_client(self):
        try:
            from py_clob_client.client import ClobClient

            funder = getattr(self.cfg, "funder_address", "") or None
            raw_sig_type = getattr(self.cfg, "signature_type", None)
            sig_type = int(raw_sig_type) if raw_sig_type is not None else None
            if funder and sig_type is not None:
                self.client = ClobClient(
                    host="https://clob.polymarket.com",
                    chain_id=137,
                    key=self.cfg.private_key,
                    signature_type=sig_type,
                    funder=funder,
                )
                log.info(f"ClobClient init | EOA signer + funder={funder[:10]}... sig_type={sig_type}")
            else:
                self.client = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=self.cfg.private_key)
            try:
                api_creds = self.client.create_or_derive_api_creds()
                self.client.set_api_creds(api_creds)
                log.info(f"Polymarket CLOB connected | API creds derived: {api_creds.api_key[:8]}...")
            except Exception as cred_err:
                log.error(f"API creds derivation failed: {cred_err}")
                if self.cfg.api_key:
                    from py_clob_client.clob_types import ApiCreds

                    creds = ApiCreds(
                        api_key=self.cfg.api_key,
                        api_secret=self.cfg.api_secret,
                        api_passphrase=self.cfg.api_passphrase,
                    )
                    self.client.set_api_creds(creds)
                    log.info("Polymarket connected with env credentials")
                else:
                    raise cred_err
        except Exception as exc:
            log.error(f"Client failed: {exc}")
            self.dry_run = True
        else:
            self._cancel_stale_open_orders()

    def _cancel_stale_open_orders(self):
        """Cancel any unfilled open orders from previous sessions to free USDC allowance."""
        try:
            from datetime import timezone as tz
            orders = self.client.get_orders() or []
            now = datetime.now(tz.utc)
            stale_ids = []
            for o in orders:
                created = o.get("created_at") or o.get("createdAt") or ""
                order_id = o.get("id") or o.get("order_id") or o.get("orderID") or ""
                if not order_id:
                    continue
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age_minutes = (now - ts).total_seconds() / 60
                    if age_minutes > 30:
                        stale_ids.append(order_id)
                except Exception:
                    stale_ids.append(order_id)
            if stale_ids:
                self.client.cancel_orders(stale_ids)
                log.info(f"Cancelled {len(stale_ids)} stale open orders on startup: {stale_ids[:3]}...")
            else:
                log.info(f"No stale open orders ({len(orders)} total open)")
        except Exception as exc:
            log.warning(f"Could not cancel stale orders (non-critical): {exc}")

    def _price_to_shares(self, price: float, size_usdc: float) -> float:
        price = max(float(price or 0), 0.01)
        return round(max(size_usdc / price, 0.0001), 4)

    def _minimum_live_exit_shares(self) -> float:
        return 5.0 if not self.dry_run else 0.0

    def _positioning_cfg(self, manager_profile: Optional[dict]) -> dict:
        return (manager_profile or {}).get("positioning", {})

    def _exits_cfg(self, manager_profile: Optional[dict]) -> dict:
        return (manager_profile or {}).get("exits", {})

    def _trade_record(self, opp, shares: float, action: str = "entry") -> TradeRecord:
        market = opp.market
        return TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            market_id=market.market_id,
            question=market.question[:100],
            side=opp.best_side,
            price=opp.best_market_price,
            size_usdc=opp.trade_size,
            edge=opp.best_edge,
            confidence=opp.confidence,
            status="pending",
            symbol=market.symbol,
            our_prob=opp.our_prob_yes,
            market_prob=opp.market_prob_yes,
            shares=shares,
            order_action=action,
        )

    def _append_trade(self, record: TradeRecord):
        self.trade_history.append(record)
        self._save_state()

    def _entry_position(self, opp, shares: float) -> Position:
        market = opp.market
        return Position(
            market_id=market.market_id,
            question=market.question[:100],
            side=opp.best_side,
            entry_price=opp.best_market_price,
            size_usdc=opp.trade_size,
            shares=shares,
            token_id=opp.best_token_id,
            symbol=market.symbol,
            edge_at_entry=opp.best_edge,
            opened_at=datetime.utcnow().isoformat(),
            last_price=opp.best_market_price,
        )

    def _place_entry_order(self, token_id: str, price: float, shares: float) -> str:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        # Market FOK: buy $amount USDC worth at the best available ask price.
        # This avoids placing limit orders below the actual ask that never fill.
        usdc_amount = round(price * shares, 4)
        order_args = MarketOrderArgs(
            token_id=token_id,
            amount=usdc_amount,
            side=BUY,
            order_type=OrderType.FOK,
        )
        order = self.client.create_market_order(order_args)
        response = self.client.post_order(order, OrderType.FOK)
        order_id = str(response.get("orderID", ""))
        # Verify the market FOK actually filled — a FOK that can't fill is silently cancelled.
        import time; time.sleep(2.0)
        try:
            order_detail = self.client.get_order(order_id)
            status = (order_detail.get("status") or "").upper()
            size_matched = float(order_detail.get("size_matched") or 0)
            log.info(f"Market order status: status={status} size_matched={size_matched}")
            if "CANCEL" in status and size_matched == 0:
                raise RuntimeError(f"Market FOK cancelled without fill: status={status}")
        except RuntimeError:
            raise
        except Exception as ve:
            log.warning(f"Order verification skipped: {ve}")
        return order_id

    def _place_exit_order(self, token_id: str, price: float, shares: float) -> str:
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import SELL

        order_args = OrderArgs(
            token_id=token_id,
            price=round(price, 4),
            size=round(shares, 4),
            side=SELL,
        )
        response = self.client.create_and_post_order(order_args)
        return str(response.get("orderID", ""))

    def _resolve_exit_price(self, pos: Position, current_price: Optional[float]) -> float:
        price = current_price or pos.last_price or pos.entry_price or 0.5
        if not self.dry_run and self.client:
            try:
                quote = self.client.get_price(pos.token_id, "SELL")
                if isinstance(quote, dict):
                    price = float(quote.get("price") or price)
            except Exception:
                pass
        return max(0.01, min(float(price), 0.99))

    def _close_position(self, pos: Position, reason: str, current_price: Optional[float]) -> bool:
        exit_price = self._resolve_exit_price(pos, current_price)
        record = TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            market_id=pos.market_id,
            question=pos.question[:100],
            side=pos.side,
            price=exit_price,
            size_usdc=pos.size_usdc,
            edge=0.0,
            confidence=reason,
            status="pending",
            symbol=pos.symbol,
            our_prob=0.0,
            market_prob=0.0,
            shares=pos.shares,
            order_action="exit",
        )
        exit_context = {
            "market_id": pos.market_id,
            "token_id": pos.token_id,
            "side": pos.side,
            "shares": round(pos.shares, 4),
            "requested_price": round(exit_price, 4),
            "entry_price": round(pos.entry_price, 4),
            "reason": reason,
        }

        min_live_shares = self._minimum_live_exit_shares()
        if min_live_shares and pos.shares < min_live_shares:
            record.status = "close_blocked_min_size"
            record.error = (
                f"Position has {pos.shares:.4f} shares, below live exit floor {min_live_shares:.1f}."
            )
            pos.status = "blocked_min_size"
            pos.last_price = exit_price
            self.trade_history.append(record)
            self._save_state()
            log.warning(
                "Exit blocked (min size) | context=%s | floor=%s",
                exit_context,
                f"{min_live_shares:.1f}",
            )
            return False

        try:
            if self.dry_run:
                record.status = "closed_dry_run"
                log.info(
                    f"[DRY RUN EXIT] {pos.side} {pos.symbol} ${pos.size_usdc:.2f} "
                    f"at {exit_price:.3f} | {reason}"
                )
            else:
                record.order_id = self._place_exit_order(pos.token_id, exit_price, pos.shares)
                record.status = "closed"
                log.info(
                    f"LIVE EXIT {pos.side} {pos.symbol} shares={pos.shares:.4f} "
                    f"order_id={record.order_id} | {reason}"
                )
        except Exception as exc:
            err_str = str(exc)
            # Phantom position: buy order was placed as limit but never filled — balance is 0 on-chain.
            # Retrying will never succeed; remove from positions so agent can seek new trades.
            if "balance: 0" in err_str or ("not enough balance" in err_str and "balance: 0" in err_str):
                record.status = "phantom_unfilled"
                record.error = err_str
                pos.status = "phantom_unfilled"
                self.trade_history.append(record)
                self.positions.pop(pos.market_id, None)
                self._save_state()
                log.warning(
                    "Phantom position detected (buy never filled) — removed | context=%s",
                    exit_context,
                )
                return False
            record.status = "close_error"
            record.error = err_str
            self.trade_history.append(record)
            self._save_state()
            log.exception(
                "Exit failed | context=%s | exception_type=%s | exception=%r",
                exit_context,
                type(exc).__name__,
                exc,
            )
            return False

        realized = (exit_price - pos.entry_price) * pos.shares
        self._daily_pnl += realized
        self.trade_history.append(record)
        self.positions.pop(pos.market_id, None)
        self._save_state()
        return True

    def _can_dca(self, existing: Position, opp, manager_profile: Optional[dict]) -> bool:
        cfg = self._positioning_cfg(manager_profile)
        if not cfg.get("dca_enabled"):
            return False
        if existing.side != opp.best_side:
            return False
        max_steps = int(cfg.get("max_dca_steps", 0) or 0)
        if existing.dca_count >= max_steps:
            return False
        improve_pct = float(cfg.get("price_improvement_for_dca", 0.03) or 0.03)
        improved_price = opp.best_market_price <= existing.entry_price * (1 - improve_pct)
        stronger_edge = opp.best_edge >= existing.edge_at_entry + 0.01
        max_position = float(cfg.get("max_size_usdc", existing.size_usdc + opp.trade_size) or existing.size_usdc + opp.trade_size)
        if existing.size_usdc + opp.trade_size > max_position:
            return False
        return improved_price or stronger_edge

    def _execute_dca(self, existing: Position, opp, manager_profile: Optional[dict]) -> TradeRecord:
        shares = self._price_to_shares(opp.best_market_price, opp.trade_size)
        record = self._trade_record(opp, shares, action="dca")
        min_live_shares = self._minimum_live_exit_shares()
        if min_live_shares and existing.shares + shares < min_live_shares:
            record.status = "skipped"
            record.error = (
                f"dca_below_min_exitable_shares:{existing.shares + shares:.4f}<{min_live_shares:.1f}"
            )
            self.trade_history.append(record)
            self._save_state()
            return record
        try:
            if self.dry_run:
                record.status = "dry_run"
                log.info(
                    f"[DRY RUN DCA] {opp.best_side} ${opp.trade_size:.2f} {opp.market.symbol} "
                    f"shares={shares:.4f} edge {opp.best_edge:.1%}"
                )
            else:
                record.order_id = self._place_entry_order(opp.best_token_id, opp.best_market_price, shares)
                record.status = "placed"
                log.info(
                    f"LIVE DCA {opp.best_side} ${opp.trade_size:.2f} {opp.market.symbol} "
                    f"shares={shares:.4f} order_id={record.order_id}"
                )
        except Exception as exc:
            record.status = "error"
            record.error = str(exc)
            self.trade_history.append(record)
            self._save_state()
            log.error(f"DCA order failed: {exc}")
            return record

        total_shares = existing.shares + shares
        weighted_entry = (
            ((existing.entry_price * existing.shares) + (opp.best_market_price * shares)) / total_shares
            if total_shares > 0
            else existing.entry_price
        )
        existing.entry_price = weighted_entry
        existing.size_usdc += opp.trade_size
        existing.shares = total_shares
        existing.edge_at_entry = max(existing.edge_at_entry, opp.best_edge)
        existing.dca_count += 1
        existing.last_price = opp.best_market_price
        self._daily_trades += 1
        self.trade_history.append(record)
        self._save_state()
        return record

    def can_trade(self):
        if date.today() != self._today:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._today = date.today()
        if self._daily_pnl <= -self.cfg.max_daily_loss:
            return False, "Daily loss limit"
        if self._daily_trades >= self.cfg.max_daily_trades:
            return False, "Daily trade limit"
        if len(self.positions) >= self.cfg.max_open_positions:
            return False, "Max positions"
        return True, "OK"

    def execute(self, opp, manager_profile: Optional[dict] = None):
        market = opp.market
        position_cfg = self._positioning_cfg(manager_profile)
        max_position_size = float(
            position_cfg.get(
                "max_size_usdc",
                getattr(self.cfg, "max_trade_usdc", opp.trade_size),
            )
            or getattr(self.cfg, "max_trade_usdc", opp.trade_size)
        )
        shares = self._price_to_shares(opp.best_market_price, opp.trade_size)
        record = self._trade_record(opp, shares)
        min_live_shares = self._minimum_live_exit_shares()
        if min_live_shares and shares < min_live_shares:
            required_size = round((min_live_shares * float(opp.best_market_price)) + 0.01, 2)
            if required_size <= max_position_size:
                opp.trade_size = max(float(opp.trade_size), required_size)
                shares = self._price_to_shares(opp.best_market_price, opp.trade_size)
                record.size_usdc = opp.trade_size
                record.shares = shares
                log.info(
                    f"Upsized live entry for {market.market_id} to ${opp.trade_size:.2f} "
                    f"to satisfy min share floor {min_live_shares:.1f}"
                )
            else:
                record.status = "skipped"
                record.error = f"below_min_exitable_shares:{shares:.4f}<{min_live_shares:.1f}"
                self.trade_history.append(record)
                self._save_state()
                log.warning(
                    f"Skipped live entry for {market.market_id}: shares={shares:.4f} below live exit floor {min_live_shares:.1f}"
                )
                return record
        existing = self.positions.get(market.market_id)
        if existing:
            if (
                existing.status == "blocked_min_size"
                and min_live_shares
                and existing.side == opp.best_side
                and existing.shares < min_live_shares
            ):
                needed_shares = max(0.0, min_live_shares - existing.shares)
                needed_size = round((needed_shares * float(opp.best_market_price)) + 0.01, 2)
                room = max(0.0, max_position_size - existing.size_usdc)
                if room > 0:
                    opp.trade_size = min(max(opp.trade_size, needed_size), room)
                    if opp.trade_size > 0:
                        log.info(
                            f"Rescue DCA for blocked position {market.market_id}: "
                            f"add ${opp.trade_size:.2f} to reach exitable size."
                        )
                        return self._execute_dca(existing, opp, manager_profile)
            if self._can_dca(existing, opp, manager_profile):
                return self._execute_dca(existing, opp, manager_profile)
            record.status = "skipped"
            record.error = "already_in"
            self.trade_history.append(record)
            self._save_state()
            return record

        ok, reason = self.can_trade()
        if not ok:
            record.status = "skipped"
            record.error = reason
            self.trade_history.append(record)
            self._save_state()
            return record

        try:
            if self.dry_run:
                log.info(
                    f"[DRY RUN] BUY {opp.best_side} ${opp.trade_size:.2f} {market.symbol} "
                    f"shares={shares:.4f} edge {opp.best_edge:.1%}"
                )
                record.status = "dry_run"
            else:
                record.order_id = self._place_entry_order(opp.best_token_id, opp.best_market_price, shares)
                record.status = "placed"
                log.info(
                    f"LIVE BUY {opp.best_side} ${opp.trade_size:.2f} {market.symbol} "
                    f"shares={shares:.4f} order_id={record.order_id}"
                )
        except Exception as exc:
            record.status = "error"
            record.error = str(exc)
            self.trade_history.append(record)
            self._save_state()
            log.error(f"Order failed: {exc}")
            return record

        self.positions[market.market_id] = self._entry_position(opp, shares)
        self._daily_trades += 1
        self.trade_history.append(record)
        self._save_state()
        return record

    def _save_state(self):
        with open(os.path.join(self.cfg.data_dir, "trades.json"), "w", encoding="utf-8") as fh:
            json.dump([asdict(t) for t in self.trade_history], fh, indent=2)
        with open(os.path.join(self.cfg.data_dir, "positions.json"), "w", encoding="utf-8") as fh:
            json.dump({key: asdict(value) for key, value in self.positions.items()}, fh, indent=2)

    def _load_state(self):
        trades_path = os.path.join(self.cfg.data_dir, "trades.json")
        positions_path = os.path.join(self.cfg.data_dir, "positions.json")
        if os.path.exists(trades_path):
            try:
                with open(trades_path, encoding="utf-8") as fh:
                    self.trade_history = [TradeRecord(**trade) for trade in json.load(fh)]
            except Exception:
                pass
        if os.path.exists(positions_path):
            try:
                with open(positions_path, encoding="utf-8") as fh:
                    self.positions = {key: Position(**value) for key, value in json.load(fh).items()}
                for pos in self.positions.values():
                    if pos.shares <= 0 and pos.entry_price > 0:
                        pos.shares = self._price_to_shares(pos.entry_price, pos.size_usdc)
            except Exception:
                pass

    def check_exits(self, market_snapshot=None, signal_map=None, manager_profile: Optional[dict] = None):
        market_snapshot = market_snapshot or {}
        signal_map = signal_map or {}
        exits_cfg = self._exits_cfg(manager_profile)
        max_hold_minutes = int(exits_cfg.get("max_hold_minutes", 180) or 180)
        profit_take_pct = float(exits_cfg.get("profit_take_pct", 0.08) or 0.08)
        profit_take_min_minutes = int(exits_cfg.get("profit_take_min_minutes", 15) or 15)
        stop_loss_pct = float(exits_cfg.get("stop_loss_pct", 0.08) or 0.08)
        exit_on_signal_flip = bool(exits_cfg.get("exit_on_signal_flip", True))
        avoid_expiry_minutes = int(exits_cfg.get("avoid_expiry_minutes", 30) or 30)
        flat_exit_minutes = int(exits_cfg.get("flat_exit_minutes", 15) or 15)
        require_profit_to_continue = bool(exits_cfg.get("require_profit_to_continue", True))
        zero_guard_price = float(exits_cfg.get("zero_guard_price", 0.08) or 0.08)

        now = datetime.utcnow()
        closed = []
        for market_id, pos in list(self.positions.items()):
            if pos.status == "blocked_min_size":
                continue
            try:
                opened = datetime.fromisoformat(pos.opened_at.replace("Z", "+00:00"))
            except Exception:
                opened = now
            held_minutes = max(0.0, (now - opened).total_seconds() / 60)

            snapshot = market_snapshot.get(market_id, {})
            current_price = snapshot.get("yes_price") if pos.side == "YES" else snapshot.get("no_price")
            if current_price is not None:
                pos.last_price = float(current_price)
            pnl_pct = None
            if current_price is not None and pos.entry_price > 0:
                pnl_pct = (float(current_price) - pos.entry_price) / pos.entry_price

            reason = ""
            if current_price is not None and current_price <= zero_guard_price:
                reason = f"Zero guard exit ({current_price:.3f})"
            elif pnl_pct is not None and pnl_pct <= -stop_loss_pct:
                reason = f"Stop loss hit ({pnl_pct:.1%})"
            elif pnl_pct is not None and held_minutes >= profit_take_min_minutes and pnl_pct >= profit_take_pct:
                reason = f"Profit locked ({pnl_pct:.1%})"
            elif require_profit_to_continue and pnl_pct is not None and held_minutes >= flat_exit_minutes and pnl_pct <= 0:
                reason = f"Flat recycle exit ({pnl_pct:.1%})"
            elif exit_on_signal_flip and signal_map.get(market_id) and signal_map[market_id].get("side") != pos.side:
                reason = "Signal flipped against position"
            elif snapshot.get("hours_to_expiry") is not None and snapshot.get("hours_to_expiry", 999) * 60 <= avoid_expiry_minutes:
                reason = "Avoiding expiry drift"
            elif held_minutes >= max_hold_minutes:
                reason = f"Max hold reached ({held_minutes:.0f}m)"

            if not reason:
                continue
            if self._close_position(pos, reason, current_price):
                closed.append((market_id, reason))
        return closed

    @property
    def stats(self):
        placed = [trade for trade in self.trade_history if trade.status in ("placed", "dry_run")]
        return {
            "total_trades": len(placed),
            "open_positions": len(self.positions),
            "deployed": sum(trade.size_usdc for trade in placed),
            "daily_pnl": self._daily_pnl,
            "mode": "DRY RUN" if self.dry_run else "LIVE",
        }
