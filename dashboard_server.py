import csv
import io
import json
import re
import sys
import threading
import webbrowser
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from manager import (
    activate_profile,
    get_manager_state,
    load_live_profile_payload,
    load_pending_profile_payload,
    patch_pending_profile,
    propose_pending_profile,
    save_profile,
    set_live_strategy_mode,
    validate_profile,
)

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
LOG_FILE = BASE / "logs" / "agent.log"
TRADING_FLAG = DATA_DIR / "trading_enabled.flag"
STRATEGY_FLAG = DATA_DIR / "strategy_mode.flag"
RUNTIME_STATS_FILE = DATA_DIR / "runtime_stats.json"
CYCLE_SUMMARY_FILE = DATA_DIR / "cycle_summary.json"
REJECTION_SUMMARY_FILE = DATA_DIR / "rejection_summary.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_env() -> dict:
    env = {}
    env_file = BASE / ".env"
    if not env_file.exists():
        return env
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _profile_wallet(env: dict) -> str:
    return env.get("POLY_FUNDER_ADDRESS", "") or env.get("POLY_SIGNER_ADDRESS", "")


def _fetch_json(url: str):
    req = Request(url, headers={"User-Agent": "POLY_AGENT/1.0"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_accounting_snapshot(wallet: str) -> dict:
    req = Request(
        f"https://data-api.polymarket.com/v1/accounting/snapshot?{urlencode({'user': wallet})}",
        headers={"User-Agent": "POLY_AGENT/1.0"},
    )
    with urlopen(req, timeout=20) as resp:
        raw = resp.read()

    parsed = {"positions": [], "equity": {}}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        if "positions.csv" in zf.namelist():
            with zf.open("positions.csv") as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"))
                parsed["positions"] = list(reader)
        if "equity.csv" in zf.namelist():
            with zf.open("equity.csv") as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"))
                parsed["equity"] = next(reader, {}) or {}
    return parsed


def trading_enabled() -> bool:
    try:
        if not TRADING_FLAG.exists():
            return True
        raw = TRADING_FLAG.read_text(encoding="utf-8", errors="ignore").strip().lower()
        return raw in ("1", "true", "yes", "on")
    except Exception:
        return True


def set_trading_enabled(enabled: bool) -> bool:
    DATA_DIR.mkdir(exist_ok=True)
    TRADING_FLAG.write_text("1" if enabled else "0", encoding="utf-8")
    return enabled


def get_strategy_mode() -> str:
    try:
        mode = load_live_profile_payload()["profile"].get("strategy_mode", "conservative")
        if mode in ("conservative", "weather_only", "crypto_only", "balanced", "legacy_aggressive"):
            return mode
    except Exception:
        pass
    return "conservative"


def set_strategy_mode(mode: str) -> str:
    return set_live_strategy_mode(mode)["profile"]["strategy_mode"]


def _to_float(value):
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("$", "")
        return float(value)
    except Exception:
        return None


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _derive_runtime_mode(env: dict) -> str:
    dry_raw = str(env.get("DRY_RUN", "")).strip().lower()
    if dry_raw in ("0", "false", "no", "off"):
        return "LIVE"
    if dry_raw in ("1", "true", "yes", "on"):
        return "DRY RUN"

    if LOG_FILE.exists():
        for line in reversed(LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-250:]):
            upper = line.upper()
            if "AGENT STARTED" in upper and "LIVE" in upper:
                return "LIVE"
            if "AGENT STARTED" in upper and "DRY RUN" in upper:
                return "DRY RUN"
    return "DRY RUN"


def _load_json_file(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except Exception:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        routes = {
            "/api/stats": self._stats,
            "/api/trades": self._trades,
            "/api/positions": self._positions,
            "/api/log": self._log,
            "/api/prices": self._prices,
            "/api/trading": self._trading,
            "/api/portfolio": self._portfolio,
            "/api/identity": self._identity,
            "/api/redeem_alerts": self._redeem_alerts,
            "/api/strategy": self._strategy,
            "/api/kpi": self._kpi,
            "/api/runtime_health": self._runtime_health,
            "/api/accountability": self._accountability,
            "/api/rejections": self._rejections,
            "/api/manager": self._manager,
            "/api/integrations": self._integrations,
        }
        if parsed.path == "/api/trading/toggle":
            query = parse_qs(parsed.query)
            enabled = (query.get("enabled", [""])[0] or "").lower() in ("1", "true", "on", "yes")
            self._json({"ok": True, "enabled": set_trading_enabled(enabled)})
        elif parsed.path == "/api/strategy/set":
            query = parse_qs(parsed.query)
            mode = query.get("mode", ["conservative"])[0]
            self._json({"ok": True, "mode": set_strategy_mode(mode)})
        elif parsed.path in routes:
            self._json(routes[parsed.path]())
        elif parsed.path == "/":
            self._file(BASE / "dashboard" / "index.html", "text/html")
        elif parsed.path == "/mgmt":
            self._file(BASE / "dashboard" / "manager.html", "text/html")
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_json_body()
        if parsed.path == "/api/manager/propose":
            pending = propose_pending_profile(body.get("proposal_text", ""), body.get("name"))
            self._json({"ok": True, "pending": pending, "state": self._manager()})
            return
        if parsed.path == "/api/manager/patch":
            patch = body.get("patch") if isinstance(body.get("patch"), dict) else {}
            pending = patch_pending_profile(
                patch,
                proposal_text=body.get("proposal_text"),
                name=body.get("name"),
            )
            self._json({"ok": True, "pending": pending, "state": self._manager()})
            return
        if parsed.path == "/api/manager/validate":
            pending = (
                propose_pending_profile(body.get("proposal_text", ""), body.get("name"))
                if body.get("proposal_text") or body.get("name")
                else load_pending_profile_payload()
            )
            validation = validate_profile(pending["profile"], self._trades())
            self._json({"ok": validation["ok"], "pending": pending, "validation": validation, "state": self._manager()})
            return
        if parsed.path == "/api/manager/save":
            pending = (
                propose_pending_profile(body.get("proposal_text", ""), body.get("name"))
                if body.get("proposal_text") or body.get("name")
                else load_pending_profile_payload()
            )
            saved = save_profile(pending["profile"])
            self._json({"ok": True, "profile": saved, "state": self._manager()})
            return
        if parsed.path == "/api/manager/activate":
            pending = (
                propose_pending_profile(body.get("proposal_text", ""), body.get("name"))
                if body.get("proposal_text") or body.get("name")
                else load_pending_profile_payload()
            )
            validation = validate_profile(pending["profile"], self._trades())
            if not validation["ok"]:
                self._json({"ok": False, "validation": validation, "state": self._manager()})
                return
            active = activate_profile(pending["profile"])
            self._json({"ok": True, "active": active, "validation": validation, "state": self._manager()})
            return
        self.send_error(404)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _trades(self):
        path = DATA_DIR / "trades.json"
        return json.load(open(path, encoding="utf-8")) if path.exists() else []

    def _positions(self):
        path = DATA_DIR / "positions.json"
        return json.load(open(path, encoding="utf-8")) if path.exists() else {}

    def _log(self):
        if not LOG_FILE.exists():
            return []
        return [line.strip() for line in LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-120:] if line.strip()]

    def _prices(self):
        prices = {"BTC": None, "ETH": None}
        if not LOG_FILE.exists():
            return prices
        for line in reversed(LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()):
            for sym in ("BTC", "ETH"):
                if prices[sym] is None:
                    m = re.search(sym + r": \$([\d,]+\.?\d*)", line)
                    if m:
                        prices[sym] = float(m.group(1).replace(",", ""))
            if prices["BTC"] and prices["ETH"]:
                break
        return prices

    def _trading(self):
        return {"enabled": trading_enabled()}

    def _strategy(self):
        return {"mode": get_strategy_mode()}

    def _identity(self):
        env = _load_env()
        expected_name = env.get("ACCOUNT_NAME", "ACCOUNT")
        funder = env.get("POLY_FUNDER_ADDRESS", "")
        signer = env.get("POLY_SIGNER_ADDRESS", "")
        has_key = bool(env.get("POLY_PRIVATE_KEY", ""))
        public_name = None
        verified_badge = False
        wallet = _profile_wallet(env)
        if wallet:
            try:
                profile = _fetch_json(
                    "https://gamma-api.polymarket.com/public-profile?"
                    + urlencode({"address": wallet})
                )
                if isinstance(profile, dict):
                    public_name = profile.get("name") or profile.get("pseudonym")
                    verified_badge = bool(profile.get("verifiedBadge"))
            except Exception:
                pass
        return {
            "expected_name": expected_name,
            "public_profile_name": public_name,
            "profile_verified_badge": verified_badge,
            "funder_wallet": funder,
            "signer_wallet": signer,
            "has_private_key": has_key,
            "env_present": bool(env),
            "verified_note": "Identity is verified by loaded wallet credentials, not public username lookup.",
        }

    def _portfolio(self):
        result = {
            "live_available": False,
            "rows": [],
            "total_value_usdc": None,
            "positions_value_usdc": None,
            "cash_balance_usdc": None,
            "equity_usdc": None,
            "redeemable_count": 0,
            "mergeable_count": 0,
            "account_name": None,
            "wallet": None,
            "source": None,
            "error": None,
        }
        env = _load_env()
        result["account_name"] = env.get("ACCOUNT_NAME", "ACCOUNT")
        wallet = _profile_wallet(env)
        result["wallet"] = wallet
        if not wallet:
            result["error"] = "No Polymarket wallet found in .env yet."
            return result
        errors = []

        try:
            positions = _fetch_json(
                "https://data-api.polymarket.com/positions?"
                + urlencode(
                    {
                        "user": wallet,
                        "limit": 30,
                        "sortBy": "CURRENT",
                        "sortDirection": "DESC",
                    }
                )
            )
            if isinstance(positions, list):
                result["rows"] = positions
                result["redeemable_count"] = sum(1 for row in positions if row.get("redeemable"))
                result["mergeable_count"] = sum(1 for row in positions if row.get("mergeable"))
                result["live_available"] = True
                result["source"] = "data-api"
        except Exception as exc:
            errors.append(f"positions: {exc}")

        try:
            value_rows = _fetch_json(
                "https://data-api.polymarket.com/value?" + urlencode({"user": wallet})
            )
            if isinstance(value_rows, list) and value_rows:
                v = _to_float(value_rows[0].get("value"))
                if v is not None:
                    result["positions_value_usdc"] = v
                    result["live_available"] = True
                    result["source"] = result["source"] or "data-api"
        except Exception as exc:
            errors.append(f"value: {exc}")

        try:
            snapshot = _fetch_accounting_snapshot(wallet)
            equity = snapshot.get("equity", {})
            cash_balance = _to_float(equity.get("cashBalance"))
            positions_value = _to_float(equity.get("positionsValue"))
            equity_total = _to_float(equity.get("equity"))

            if cash_balance is not None:
                result["cash_balance_usdc"] = cash_balance
            if positions_value is not None:
                result["positions_value_usdc"] = positions_value
            if equity_total is not None:
                result["equity_usdc"] = equity_total
                result["total_value_usdc"] = equity_total
            elif positions_value is not None:
                result["total_value_usdc"] = positions_value

            if cash_balance is not None or positions_value is not None:
                result["live_available"] = True
                result["source"] = "accounting-snapshot"
        except Exception as exc:
            errors.append(f"accounting snapshot: {exc}")

        if result["total_value_usdc"] is None and result["positions_value_usdc"] is not None:
            result["total_value_usdc"] = result["positions_value_usdc"]

        if not result["live_available"] and errors:
            result["error"] = " | ".join(errors)
        return result

    def _redeem_alerts(self):
        alerts = []
        env = _load_env()
        wallet = _profile_wallet(env)
        if wallet:
            try:
                positions = _fetch_json(
                    "https://data-api.polymarket.com/positions?"
                    + urlencode(
                        {
                            "user": wallet,
                            "limit": 25,
                            "sortBy": "CURRENT",
                            "sortDirection": "DESC",
                        }
                    )
                )
                if isinstance(positions, list):
                    redeemable = [p for p in positions if p.get("redeemable")]
                    for row in redeemable[:6]:
                        title = row.get("title", "Redeemable position")
                        outcome = row.get("outcome", "position")
                        value = _to_float(row.get("currentValue")) or 0.0
                        alerts.append(
                            {
                                "severity": "warn",
                                "message": f"Redeem available: {title} ({outcome}) worth about ${value:.2f}.",
                            }
                        )
            except Exception:
                pass

        positions = self._positions()
        now = _utc_now()
        for market_id, pos in positions.items():
            opened = pos.get("opened_at", "")
            opened_dt = None
            try:
                opened_dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
            except Exception:
                pass
            if opened_dt and now - opened_dt > timedelta(hours=20):
                alerts.append(
                    {
                        "market_id": market_id,
                        "question": pos.get("question", ""),
                        "severity": "warn",
                        "message": "Position older than 20h. Check if market resolved and claim/redeem proceeds.",
                    }
                )
        if not alerts:
            alerts.append({"severity": "ok", "message": "No immediate redeem alerts from local positions."})
        return {"alerts": alerts[:20]}

    def _kpi(self):
        trades = self._trades()
        runtime = _load_json_file(RUNTIME_STATS_FILE, {})
        executed = [t for t in trades if t.get("status") in ("placed", "dry_run")]
        total = len(executed)
        win_like = sum(1 for t in executed if t.get("edge", 0) > 0)
        win_rate = round((win_like / total) * 100, 2) if total else 0.0
        avg_edge = round(sum(t.get("edge", 0) for t in executed) / total, 4) if total else 0.0

        # Build a simple cumulative expected PnL curve from edge*size.
        curve = []
        running = 0.0
        for t in executed:
            running += float(t.get("edge", 0) or 0) * float(t.get("size_usdc", 0) or 0)
            curve.append(running)
        peak = curve[0] if curve else 0.0
        max_dd = 0.0
        for v in curve:
            if v > peak:
                peak = v
            dd = peak - v
            if dd > max_dd:
                max_dd = dd

        last20 = executed[-20:]
        recent_wr = round((sum(1 for t in last20 if t.get("edge", 0) > 0) / len(last20)) * 100, 2) if last20 else 0.0

        return {
            "strategy_mode": get_strategy_mode(),
            "trading_enabled": trading_enabled(),
            "total_executed": total,
            "win_rate_pct": win_rate,
            "recent_20_win_rate_pct": recent_wr,
            "avg_edge": avg_edge,
            "max_drawdown_est": round(max_dd, 4),
            "runtime_health_reason": runtime.get("runtime_health_reason"),
            "idle_minutes_since_last_live_order": runtime.get("idle_minutes_since_last_live_order"),
            "last_live_entry_at": runtime.get("last_live_entry_at"),
            "last_live_exit_at": runtime.get("last_live_exit_at"),
            "blocked_exit_count": runtime.get("blocked_exit_count", 0),
            "trapped_position_count": runtime.get("trapped_position_count", 0),
            "unrealized_pnl_open": runtime.get("unrealized_pnl_open", 0.0),
            "profit_by_symbol_bucket": runtime.get("profit_by_symbol_bucket", {}),
        }

    def _runtime_health(self):
        runtime = _load_json_file(RUNTIME_STATS_FILE, {})
        return {
            "mode": runtime.get("mode", "DRY RUN"),
            "runtime_health_reason": runtime.get("runtime_health_reason"),
            "idle_minutes_since_last_live_order": runtime.get("idle_minutes_since_last_live_order"),
            "last_live_entry_at": runtime.get("last_live_entry_at"),
            "last_live_exit_at": runtime.get("last_live_exit_at"),
            "orders_placed_today": runtime.get("orders_placed_today", 0),
            "orders_closed_today": runtime.get("orders_closed_today", 0),
            "blocked_entry_count": runtime.get("blocked_entry_count", 0),
            "blocked_exit_count": runtime.get("blocked_exit_count", 0),
            "exit_failure_count": runtime.get("exit_failure_count", 0),
            "trapped_position_count": runtime.get("trapped_position_count", 0),
            "unrealized_pnl_open": runtime.get("unrealized_pnl_open", 0.0),
        }

    def _accountability(self):
        runtime = _load_json_file(RUNTIME_STATS_FILE, {})
        cycle = _load_json_file(CYCLE_SUMMARY_FILE, {})
        return {
            "runtime_health_reason": runtime.get("runtime_health_reason"),
            "orders_placed_today": runtime.get("orders_placed_today", 0),
            "orders_closed_today": runtime.get("orders_closed_today", 0),
            "last_live_entry_at": runtime.get("last_live_entry_at"),
            "last_live_exit_at": runtime.get("last_live_exit_at"),
            "idle_minutes_since_last_live_order": runtime.get("idle_minutes_since_last_live_order"),
            "blocked_entry_count": runtime.get("blocked_entry_count", 0),
            "blocked_exit_count": runtime.get("blocked_exit_count", 0),
            "exit_failure_count": runtime.get("exit_failure_count", 0),
            "trapped_position_count": runtime.get("trapped_position_count", 0),
            "unrealized_pnl_open": runtime.get("unrealized_pnl_open", 0.0),
            "profit_by_symbol_bucket": runtime.get("profit_by_symbol_bucket", {}),
            "latest_cycle": cycle,
        }

    def _rejections(self):
        return _load_json_file(
            REJECTION_SUMMARY_FILE,
            {
                "message": "No rejection summary persisted yet.",
                "markets_seen": 0,
            },
        )

    def _manager(self):
        return get_manager_state(
            self._trades(),
            self._positions(),
            stats=self._stats(),
            kpi=self._kpi(),
        )

    def _integrations(self):
        env = _load_env()
        live = load_live_profile_payload()
        tradingview_symbol = env.get("TRADINGVIEW_DEFAULT_SYMBOL", "BINANCE:BTCUSDT")
        tradingview_library = _truthy(env.get("TRADINGVIEW_CHARTING_LIBRARY_ACCESS", ""))
        weathercom_ready = bool(env.get("WEATHERCOM_API_KEY", "").strip())
        weatherapi_ready = bool(env.get("WEATHERAPI_RAPIDAPI_KEY", "").strip())
        chatgpt_thread = env.get("CHATGPT_DEV_THREAD_URL", "").strip()

        return {
            "weather": {
                "noaa": {
                    "enabled": True,
                    "configured": True,
                    "docs_url": "https://www.weather.gov/documentation/services-web-api",
                    "endpoint": "https://api.weather.gov/points/{lat},{lon}",
                    "coverage": "Best for U.S. locations and alerts.",
                },
                "weather_company": {
                    "enabled": weathercom_ready,
                    "configured": weathercom_ready,
                    "docs_url": "https://developer.weather.com/docs/standard-weather-data-package",
                    "endpoint": "https://api.weather.com/v3/wx/forecast/hourly/2day",
                    "coverage": "Optional key-backed source for broader hourly coverage.",
                },
                "weatherapi_rapidapi": {
                    "enabled": weatherapi_ready,
                    "configured": weatherapi_ready,
                    "docs_url": "https://rapidapi.com/weatherapi/api/weatherapi-com",
                    "endpoint": "https://weatherapi-com.p.rapidapi.com/forecast.json",
                    "host": env.get("WEATHERAPI_RAPIDAPI_HOST", "weatherapi-com.p.rapidapi.com"),
                    "coverage": "Optional global current + forecast feed through RapidAPI.",
                },
                "notes": [
                    "Consumer weather.com pages are not scraped in this build.",
                    "WeatherAPI.com via RapidAPI is separate from weather.com / The Weather Company.",
                    "Official NOAA data stays public; the key-backed providers are optional overlays.",
                ],
            },
            "tradingview": {
                "enabled": True,
                "default_symbol": tradingview_symbol,
                "docs_url": "https://www.tradingview.com/widget-docs/widgets/charts",
                "integration_mode": "charting-library" if tradingview_library else "widget",
                "charting_library_access": tradingview_library,
                "library_path": env.get("TRADINGVIEW_LIBRARY_PATH", "").strip(),
                "live_reference_requested": bool(
                    live.get("profile", {}).get("analysis", {}).get("use_tradingview_reference", False)
                ),
                "notes": [
                    "The official embed widget is wired for the MGMT UI.",
                    "The full Charting Library still needs separate TradingView access approval.",
                ],
            },
            "news": {
                "google_news_rss": {
                    "enabled": True,
                    "configured": True,
                    "source": "Google News RSS search",
                }
            },
            "chatgpt": {
                "configured": bool(chatgpt_thread),
                "thread_url": chatgpt_thread,
                "note": "Set CHATGPT_DEV_THREAD_URL in .env if you want the manager panel to link to it.",
            },
        }

    def _stats(self):
        trades = self._trades()
        positions = self._positions()
        runtime = _load_json_file(RUNTIME_STATS_FILE, {})
        placed = [t for t in trades if t.get("status") == "placed"]
        pnl = sum(t.get("edge", 0) * t.get("size_usdc", 0) for t in placed)
        today = _utc_now().date().isoformat()
        today_trades = [t for t in placed if t.get("timestamp", "").startswith(today)]
        env = _load_env()
        mode = _derive_runtime_mode(env)

        total_val = sum(t.get("size_usdc", 0) for t in placed)
        win_rate = round(sum(1 for t in placed if t.get("edge", 0) > 0.06) / len(placed) * 100, 1) if placed else 0
        return {
            "account": env.get("ACCOUNT_NAME", "ACCOUNT"),
            "wallet": env.get("POLY_FUNDER_ADDRESS", ""),
            "total_trades": len(placed),
            "open_positions": len(positions),
            "total_deployed": total_val,
            "estimated_pnl": round(pnl, 2),
            "today_trades": len(today_trades),
            "today_deployed": sum(t.get("size_usdc", 0) for t in today_trades),
            "win_rate": win_rate,
            "mode": mode,
            "trading_enabled": trading_enabled(),
            "strategy_mode": get_strategy_mode(),
            "runtime_health_reason": runtime.get("runtime_health_reason"),
            "orders_placed_today": runtime.get("orders_placed_today", 0),
            "orders_closed_today": runtime.get("orders_closed_today", 0),
            "last_live_entry_at": runtime.get("last_live_entry_at"),
            "last_live_exit_at": runtime.get("last_live_exit_at"),
            "idle_minutes_since_last_live_order": runtime.get("idle_minutes_since_last_live_order"),
            "blocked_entry_count": runtime.get("blocked_entry_count", 0),
            "blocked_exit_count": runtime.get("blocked_exit_count", 0),
            "exit_failure_count": runtime.get("exit_failure_count", 0),
            "trapped_position_count": runtime.get("trapped_position_count", 0),
            "unrealized_pnl_open": runtime.get("unrealized_pnl_open", 0.0),
            "profit_by_symbol_bucket": runtime.get("profit_by_symbol_bucket", {}),
            "last_updated": _utc_now().isoformat(),
        }


def run():
    server = HTTPServer(("0.0.0.0", 7731), H)
    target_path = "/mgmt" if "--mgmt" in sys.argv[1:] else "/"
    local_ip = "192.168.4.106"
    base_url = "http://localhost:7731"
    print(f"Dashboard at {base_url}")
    print(f"Manager UI at {base_url}/mgmt")
    print(f"Mobile (same WiFi): http://{local_ip}:7731/mgmt")
    try:
        threading.Timer(1.5, lambda: webbrowser.open(base_url + target_path)).start()
    except Exception:
        pass
    server.serve_forever()


if __name__ == "__main__":
    run()
