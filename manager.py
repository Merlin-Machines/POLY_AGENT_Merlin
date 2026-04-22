import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
PROFILES_FILE = DATA_DIR / "manager_profiles.json"
ACTIVE_FILE = DATA_DIR / "manager_active.json"
PENDING_FILE = DATA_DIR / "manager_pending.json"
STRATEGY_FLAG = DATA_DIR / "strategy_mode.flag"

ALLOWED_STRATEGY_MODES = (
    "conservative",
    "weather_only",
    "crypto_only",
    "balanced",
    "legacy_aggressive",
)

DEFAULT_PENDING_PROPOSAL_TEXT = (
    "Continuously trade short-duration setups with 5-minute candles, MACD, RA/RSI, "
    "Bollinger Bands, momentum, trend, and TradingView-style confirmation when "
    "available. Use live weather and news context where helpful. Enter and exit YES "
    "or NO positions more actively, avoid holding into expiry, allow careful DCA "
    "adds, enforce stop losses, keep cycling capital instead of drifting toward "
    "zero, review performance every cycle, and track a $100 by Friday stretch "
    "target without assuming certainty."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return deepcopy(default)


def _write_json(path: Path, payload):
    DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _clamp(value, low, high):
    return max(low, min(high, value))


def _strategy_from_flag() -> str:
    try:
        raw = STRATEGY_FLAG.read_text(encoding="utf-8", errors="ignore").strip().lower()
        if raw in ALLOWED_STRATEGY_MODES:
            return raw
    except Exception:
        pass
    return "conservative"


def _coerce_float(value, default):
    try:
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        return float(value)
    except Exception:
        return float(default)


def _coerce_int(value, default):
    try:
        return int(float(value))
    except Exception:
        return int(default)


def default_profile(name: str = "runtime-default") -> dict:
    return {
        "name": name,
        "summary": "Live manager directive profile.",
        "proposal_text": "",
        "strategy_mode": _strategy_from_flag(),
        "control": {
            "approval_required": False,
            "auto_apply_directives": True,
            "script_editing_allowed": True,
        },
        "market_filters": {
            "crypto": True,
            "weather": True,
        },
        "analysis": {
            "candle_interval": "5m",
            "use_macd": True,
            "use_rsi": True,
            "use_ra": True,
            "use_bollinger": True,
            "use_trend": True,
            "use_news_context": True,
            "use_weather_context": True,
            "use_tradingview_reference": False,
            "alignment_required": 3,
        },
        "entry": {
            "continuous_trading": False,
            "min_edge_crypto": 0.04,
            "min_edge_weather": 0.05,
            "min_prob_crypto": 0.55,
            "min_prob_weather": 0.60,
            "max_entries_per_cycle": 3,
        },
        "positioning": {
            "base_size_usdc": 1.0,
            "max_size_usdc": 3.0,
            "dca_enabled": False,
            "max_dca_steps": 0,
            "price_improvement_for_dca": 0.03,
        },
        "exits": {
            "max_hold_minutes": 90,
            "profit_take_pct": 0.04,
            "profit_take_min_minutes": 8,
            "stop_loss_pct": 0.05,
            "exit_on_signal_flip": True,
            "avoid_expiry_minutes": 45,
            "flat_exit_minutes": 15,
            "require_profit_to_continue": True,
            "zero_guard_price": 0.08,
        },
        "goals": {
            "target_profit_by_friday_usdc": 100.0,
            "stretch_win_rate_pct": 100.0,
        },
        "review": {
            "enabled": True,
            "cadence": "cycle",
            "coaching_tone": "firm",
        },
        "notes": [],
    }


def normalize_profile(profile: dict | None) -> dict:
    merged = _merge_dicts(default_profile((profile or {}).get("name", "runtime-default")), profile or {})
    merged["strategy_mode"] = (
        merged.get("strategy_mode", "conservative")
        if merged.get("strategy_mode") in ALLOWED_STRATEGY_MODES
        else "conservative"
    )

    analysis = merged["analysis"]
    analysis["candle_interval"] = "5m"
    analysis["use_macd"] = bool(analysis.get("use_macd", True))
    analysis["use_rsi"] = bool(analysis.get("use_rsi", True))
    analysis["use_ra"] = bool(analysis.get("use_ra", analysis["use_rsi"]))
    analysis["use_bollinger"] = bool(analysis.get("use_bollinger", True))
    analysis["use_trend"] = bool(analysis.get("use_trend", True))
    analysis["use_news_context"] = bool(analysis.get("use_news_context", True))
    analysis["use_weather_context"] = bool(analysis.get("use_weather_context", True))
    analysis["use_tradingview_reference"] = bool(analysis.get("use_tradingview_reference", False))
    analysis["alignment_required"] = _clamp(_coerce_int(analysis.get("alignment_required", 3), 3), 1, 5)

    control = merged["control"]
    control["approval_required"] = bool(control.get("approval_required", False))
    control["auto_apply_directives"] = bool(control.get("auto_apply_directives", True))
    control["script_editing_allowed"] = bool(control.get("script_editing_allowed", True))

    entry = merged["entry"]
    entry["continuous_trading"] = bool(entry.get("continuous_trading", False))
    entry["min_edge_crypto"] = _clamp(_coerce_float(entry.get("min_edge_crypto", 0.04), 0.04), 0.005, 0.20)
    entry["min_edge_weather"] = _clamp(_coerce_float(entry.get("min_edge_weather", 0.05), 0.05), 0.005, 0.20)
    entry["min_prob_crypto"] = _clamp(_coerce_float(entry.get("min_prob_crypto", 0.55), 0.55), 0.50, 0.95)
    entry["min_prob_weather"] = _clamp(_coerce_float(entry.get("min_prob_weather", 0.60), 0.60), 0.50, 0.95)
    entry["max_entries_per_cycle"] = _clamp(_coerce_int(entry.get("max_entries_per_cycle", 2), 2), 1, 5)

    positioning = merged["positioning"]
    positioning["base_size_usdc"] = _clamp(_coerce_float(positioning.get("base_size_usdc", 1.0), 1.0), 0.5, 10.0)
    positioning["max_size_usdc"] = _clamp(_coerce_float(positioning.get("max_size_usdc", 3.0), 3.0), 1.0, 20.0)
    if positioning["max_size_usdc"] < positioning["base_size_usdc"]:
        positioning["max_size_usdc"] = positioning["base_size_usdc"]
    positioning["dca_enabled"] = bool(positioning.get("dca_enabled", False))
    positioning["max_dca_steps"] = _clamp(_coerce_int(positioning.get("max_dca_steps", 0), 0), 0, 4)
    positioning["price_improvement_for_dca"] = _clamp(
        _coerce_float(positioning.get("price_improvement_for_dca", 0.03), 0.03),
        0.0,
        0.25,
    )

    exits = merged["exits"]
    exits["max_hold_minutes"] = _clamp(_coerce_int(exits.get("max_hold_minutes", 180), 180), 15, 720)
    exits["profit_take_pct"] = _clamp(_coerce_float(exits.get("profit_take_pct", 0.08), 0.08), 0.01, 0.50)
    exits["profit_take_min_minutes"] = _clamp(
        _coerce_int(exits.get("profit_take_min_minutes", 15), 15),
        0,
        exits["max_hold_minutes"],
    )
    exits["stop_loss_pct"] = _clamp(_coerce_float(exits.get("stop_loss_pct", 0.08), 0.08), 0.01, 0.50)
    exits["exit_on_signal_flip"] = bool(exits.get("exit_on_signal_flip", True))
    exits["avoid_expiry_minutes"] = _clamp(_coerce_int(exits.get("avoid_expiry_minutes", 30), 30), 5, 180)
    exits["flat_exit_minutes"] = _clamp(_coerce_int(exits.get("flat_exit_minutes", 15), 15), 1, exits["max_hold_minutes"])
    exits["require_profit_to_continue"] = bool(exits.get("require_profit_to_continue", True))
    exits["zero_guard_price"] = _clamp(_coerce_float(exits.get("zero_guard_price", 0.08), 0.08), 0.01, 0.25)

    merged["market_filters"]["crypto"] = bool(merged["market_filters"].get("crypto", True))
    merged["market_filters"]["weather"] = bool(merged["market_filters"].get("weather", True))

    goals = merged["goals"]
    goals["target_profit_by_friday_usdc"] = _clamp(
        _coerce_float(goals.get("target_profit_by_friday_usdc", 100.0), 100.0),
        0.0,
        100000.0,
    )
    goals["stretch_win_rate_pct"] = _clamp(
        _coerce_float(goals.get("stretch_win_rate_pct", 100.0), 100.0),
        0.0,
        100.0,
    )

    merged["review"]["enabled"] = bool(merged["review"].get("enabled", True))
    merged["review"]["cadence"] = str(merged["review"].get("cadence", "cycle") or "cycle")
    merged["review"]["coaching_tone"] = str(merged["review"].get("coaching_tone", "firm") or "firm")
    merged["notes"] = [str(note) for note in merged.get("notes", []) if str(note).strip()]
    return merged


def load_profiles() -> dict:
    profiles = _read_json(PROFILES_FILE, {})
    if not profiles:
        base = default_profile()
        profiles = {
            base["name"]: base,
        }
        _write_json(PROFILES_FILE, profiles)
    normalized = {name: normalize_profile(profile) for name, profile in profiles.items()}
    if normalized != profiles:
        _write_json(PROFILES_FILE, normalized)
    return normalized


def save_profile(profile: dict) -> dict:
    normalized = normalize_profile(profile)
    profiles = load_profiles()
    profiles[normalized["name"]] = normalized
    _write_json(PROFILES_FILE, profiles)
    return normalized


def load_active_profile_payload() -> dict:
    payload = _read_json(ACTIVE_FILE, {})
    if not payload:
        profiles = load_profiles()
        profile = normalize_profile(profiles.get("runtime-default") or next(iter(profiles.values())))
        payload = {
            "name": profile["name"],
            "profile": profile,
            "activated_at": _utc_now_iso(),
        }
        _write_json(ACTIVE_FILE, payload)
    payload["profile"] = normalize_profile(payload.get("profile"))
    payload["name"] = payload["profile"]["name"]
    return payload


def load_active_profile() -> dict:
    return load_active_profile_payload()["profile"]


def load_live_profile_payload() -> dict:
    active = load_active_profile_payload()
    pending = load_pending_profile_payload()
    pending_profile = normalize_profile(pending.get("profile"))
    if pending_profile.get("control", {}).get("auto_apply_directives", True):
        return {
            "name": pending_profile["name"],
            "profile": pending_profile,
            "activated_at": pending.get("updated_at") or pending.get("created_at") or _utc_now_iso(),
            "source": "pending-directive",
        }
    return {
        "name": active["name"],
        "profile": normalize_profile(active.get("profile")),
        "activated_at": active.get("activated_at") or _utc_now_iso(),
        "source": "saved-baseline",
    }


def load_live_profile() -> dict:
    return load_live_profile_payload()["profile"]


def activate_profile(profile: dict, name: str | None = None) -> dict:
    normalized = normalize_profile(profile)
    if name:
        normalized["name"] = name
    save_profile(normalized)
    payload = {
        "name": normalized["name"],
        "profile": normalized,
        "activated_at": _utc_now_iso(),
    }
    _write_json(ACTIVE_FILE, payload)
    try:
        STRATEGY_FLAG.write_text(normalized["strategy_mode"], encoding="utf-8")
    except Exception:
        pass
    return payload


def load_pending_profile_payload() -> dict:
    pending = _read_json(PENDING_FILE, {})
    if not pending:
        base = load_active_profile()
        proposed = propose_profile_from_text(DEFAULT_PENDING_PROPOSAL_TEXT, base)
        pending = {
            "name": proposed["name"],
            "proposal_text": DEFAULT_PENDING_PROPOSAL_TEXT,
            "profile": proposed,
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        }
        _write_json(PENDING_FILE, pending)
    pending["profile"] = normalize_profile(pending.get("profile"))
    pending["name"] = pending["profile"]["name"]
    return pending


def save_pending_profile(payload: dict) -> dict:
    persisted = {
        "name": payload["profile"]["name"],
        "proposal_text": payload.get("proposal_text", ""),
        "profile": normalize_profile(payload["profile"]),
        "created_at": payload.get("created_at") or _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    }
    _write_json(PENDING_FILE, persisted)
    return persisted


def patch_pending_profile(
    patch: dict | None = None,
    *,
    proposal_text: str | None = None,
    name: str | None = None,
) -> dict:
    pending = load_pending_profile_payload()
    profile = normalize_profile(pending.get("profile"))
    profile = _merge_dicts(profile, patch or {})
    if proposal_text is not None:
        profile["proposal_text"] = proposal_text
    if name:
        profile["name"] = _slugify(name)

    pending["profile"] = normalize_profile(profile)
    pending["name"] = pending["profile"]["name"]
    if proposal_text is not None:
        pending["proposal_text"] = proposal_text
    elif not pending.get("proposal_text"):
        pending["proposal_text"] = pending["profile"].get("proposal_text", "")

    persisted = save_pending_profile(pending)
    try:
        STRATEGY_FLAG.write_text(persisted["profile"]["strategy_mode"], encoding="utf-8")
    except Exception:
        pass
    return persisted


def _slugify(name: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return raw or f"profile-{_utc_now().strftime('%Y%m%d-%H%M%S')}"


def propose_profile_from_text(text: str, active_profile: dict | None = None, name: str | None = None) -> dict:
    profile = normalize_profile(active_profile or default_profile())
    lower = (text or "").lower()
    profile["proposal_text"] = text or ""
    profile["summary"] = "Manager proposal generated from freeform strategy notes."
    profile["name"] = _slugify(name or "continuous-profit-manager")

    if any(token in lower for token in ("5 min", "5-minute", "5minute", "five minute")):
        profile["analysis"]["candle_interval"] = "5m"
    if "macd" in lower:
        profile["analysis"]["use_macd"] = True
    if "rsi" in lower or re.search(r"\bra\b", lower):
        profile["analysis"]["use_rsi"] = True
        profile["analysis"]["use_ra"] = True
    if "bollinger" in lower or "bands" in lower:
        profile["analysis"]["use_bollinger"] = True
    if "tradingview" in lower:
        profile["analysis"]["use_tradingview_reference"] = True
        profile["notes"].append("TradingView requested; current build uses local indicator parity, not a live TradingView connector.")
    if "news" in lower:
        profile["analysis"]["use_news_context"] = True
    if "weather" in lower:
        profile["analysis"]["use_weather_context"] = True
    if any(token in lower for token in ("not approving", "no approval", "doesnt need approval", "doesn't need approval")):
        profile["control"]["approval_required"] = False
        profile["control"]["auto_apply_directives"] = True
        profile["control"]["script_editing_allowed"] = True

    if any(token in lower for token in ("continuous", "always be trading", "continuously")):
        profile["entry"]["continuous_trading"] = True
        profile["entry"]["max_entries_per_cycle"] = max(profile["entry"]["max_entries_per_cycle"], 4)
        profile["strategy_mode"] = "crypto_only"
        profile["market_filters"]["crypto"] = True
        profile["market_filters"]["weather"] = False
        profile["analysis"]["alignment_required"] = max(profile["analysis"]["alignment_required"], 3)

    if any(token in lower for token in ("yes or no", "yes/no", "whether yes or no")):
        profile["summary"] = "Active YES/NO runtime profile for short-duration opportunities."

    if any(token in lower for token in ("dollar cost averaging", "dca")):
        profile["positioning"]["dca_enabled"] = True
        profile["positioning"]["max_dca_steps"] = 2
        profile["positioning"]["price_improvement_for_dca"] = 0.03

    if any(token in lower for token in ("stop loss", "stop losses")):
        profile["exits"]["stop_loss_pct"] = 0.05

    if any(token in lower for token in ("never stay in trades until expiration", "never stay in trades", "avoid expiry", "holding into expiry", "expiration")):
        profile["exits"]["max_hold_minutes"] = 45
        profile["exits"]["avoid_expiry_minutes"] = 60
        profile["exits"]["profit_take_min_minutes"] = 5
        profile["exits"]["flat_exit_minutes"] = 10
        profile["exits"]["zero_guard_price"] = 0.08
        profile["exits"]["require_profit_to_continue"] = True

    if any(token in lower for token in ("scraping profit", "certain profits", "certain profit")):
        profile["entry"]["min_edge_crypto"] = 0.05
        profile["entry"]["min_prob_crypto"] = 0.60
        profile["exits"]["profit_take_pct"] = 0.03
        profile["exits"]["flat_exit_minutes"] = 8
        profile["exits"]["require_profit_to_continue"] = True
        profile["notes"].append("Profit scraping tightened thresholds, but certainty is treated as a high-confidence proxy rather than a guarantee.")

    if "100 dollars by friday" in lower or "$100 by friday" in lower:
        profile["goals"]["target_profit_by_friday_usdc"] = 100.0
    if "100% win rate" in lower or "100 percent win rate" in lower:
        profile["goals"]["stretch_win_rate_pct"] = 100.0
        profile["notes"].append("100% win rate is stored as a stretch goal only, not an execution assumption.")

    if any(token in lower for token in ("performance review", "performance reviews", "feedback", "coaching")):
        profile["review"]["enabled"] = True
        profile["review"]["cadence"] = "cycle"
        profile["review"]["coaching_tone"] = "firm"

    profile["analysis"]["alignment_required"] = max(int(profile["analysis"].get("alignment_required", 3) or 3), 3)
    profile["positioning"]["base_size_usdc"] = 1.25
    profile["positioning"]["max_size_usdc"] = 3.0
    return normalize_profile(profile)


def compute_profile_diff(current_profile: dict, proposed_profile: dict) -> list[dict]:
    diffs = []

    def walk(prefix: str, before, after):
        if isinstance(before, dict) and isinstance(after, dict):
            keys = sorted(set(before) | set(after))
            for key in keys:
                next_prefix = f"{prefix}.{key}" if prefix else key
                walk(next_prefix, before.get(key), after.get(key))
            return
        if before != after:
            diffs.append({"field": prefix, "from": before, "to": after})

    walk("", normalize_profile(current_profile), normalize_profile(proposed_profile))
    return diffs


def _next_friday(today: date | None = None) -> date:
    today = today or date.today()
    days_ahead = (4 - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


def replay_profile(profile: dict, trades: list[dict]) -> dict:
    normalized = normalize_profile(profile)
    executed = [
        t for t in trades
        if t.get("status") in ("placed", "dry_run") and t.get("order_action", "entry") != "exit"
    ]

    qualified = []
    for trade in executed:
        symbol = str(trade.get("symbol", "")).upper()
        if symbol == "CRYPTO" and not normalized["market_filters"]["crypto"]:
            continue
        if symbol == "WEATHER" and not normalized["market_filters"]["weather"]:
            continue
        edge = _coerce_float(trade.get("edge", 0), 0.0)
        min_edge = normalized["entry"]["min_edge_crypto"] if symbol == "CRYPTO" else normalized["entry"]["min_edge_weather"]
        if edge < min_edge:
            continue
        size_usdc = min(_coerce_float(trade.get("size_usdc", 0), 0.0), normalized["positioning"]["max_size_usdc"])
        qualified.append({"edge": edge, "size_usdc": size_usdc})

    est_pnl = sum(item["edge"] * item["size_usdc"] for item in qualified)
    win_rate = round(sum(1 for item in qualified if item["edge"] > 0) / len(qualified) * 100, 2) if qualified else 0.0
    return {
        "sample_size": len(executed),
        "qualified_trades": len(qualified),
        "estimated_pnl_usdc": round(est_pnl, 2),
        "estimated_win_rate_pct": win_rate,
    }


def validate_profile(profile: dict, trades: list[dict] | None = None) -> dict:
    normalized = normalize_profile(profile)
    errors = []
    warnings = []

    if normalized["analysis"]["candle_interval"] != "5m":
        errors.append("Manager runtime only supports 5-minute candles in this build.")
    if not normalized["market_filters"]["crypto"] and not normalized["market_filters"]["weather"]:
        errors.append("At least one market filter must remain enabled.")
    if normalized["positioning"]["dca_enabled"] and normalized["positioning"]["max_dca_steps"] <= 0:
        errors.append("DCA is enabled but max DCA steps is zero.")
    if normalized["positioning"]["max_size_usdc"] < normalized["positioning"]["base_size_usdc"]:
        errors.append("Max size cannot be smaller than base size.")

    if normalized["analysis"]["use_tradingview_reference"]:
        warnings.append("TradingView is not wired as a live data source here; the agent still uses local indicators and exchange feeds.")
    if not normalized["control"]["approval_required"]:
        warnings.append("Manager directives are auto-live in this build, so versioning and the dashboard trading toggle matter even more.")
    if normalized["goals"]["stretch_win_rate_pct"] >= 100:
        warnings.append("A 100% win-rate goal is stored as a stretch target only. The manager should optimize expectancy and drawdown, not assume certainty.")
    if normalized["goals"]["target_profit_by_friday_usdc"] > 0:
        target_date = _next_friday().isoformat()
        warnings.append(f"Friday profit targets are tracked operationally, but they are not guaranteed. Current target date: {target_date}.")
    if normalized["entry"]["continuous_trading"]:
        warnings.append("Continuous trading mode increases opportunity throughput; keep the trading toggle and dry-run checks ready because directives are live immediately.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "replay": replay_profile(normalized, trades or []),
    }


def build_review(profile: dict, trades: list[dict], positions: dict, stats: dict | None = None, kpi: dict | None = None) -> dict:
    normalized = normalize_profile(profile)
    stats = stats or {}
    kpi = kpi or {}

    estimated_pnl = _coerce_float(stats.get("estimated_pnl", 0), 0.0)
    target_profit = normalized["goals"]["target_profit_by_friday_usdc"]
    win_rate = _coerce_float(kpi.get("win_rate_pct", 0), 0.0)
    recent_win_rate = _coerce_float(kpi.get("recent_20_win_rate_pct", 0), 0.0)
    avg_edge_pct = _coerce_float(kpi.get("avg_edge", 0), 0.0) * 100
    goal_pct = round((estimated_pnl / target_profit) * 100, 1) if target_profit else 0.0
    friday = _next_friday().isoformat()

    reinforcements = []
    coaching = []
    risks = []

    if estimated_pnl > 0:
        reinforcements.append(f"Positive expected P&L is on the board at ${estimated_pnl:.2f}.")
    else:
        coaching.append("No positive expected P&L buffer yet. Tighten entries before increasing turnover.")

    if recent_win_rate >= 55:
        reinforcements.append(f"Recent execution quality is holding at {recent_win_rate:.2f}% over the last 20 signals.")
    else:
        coaching.append(f"Recent win rate is {recent_win_rate:.2f}%. Review signal alignment before adding more size.")

    if positions:
        coaching.append(f"{len(positions)} positions are open. Keep the hold cap honest and avoid drifting toward expiry.")
    else:
        reinforcements.append("No open local positions are drifting unmanaged right now.")

    if avg_edge_pct < 4:
        risks.append("Average edge is thin. Continuous mode should not degrade entry quality just to stay active.")
    if normalized["goals"]["stretch_win_rate_pct"] >= 100:
        risks.append("The 100% win-rate target is unrealistic as an operational metric. Treat it as a motivational banner, not a hard promise.")

    scorecard = [
        f"Goal progress: ${estimated_pnl:.2f} / ${target_profit:.2f} by {friday} ({goal_pct:.1f}%).",
        f"Win rate: {win_rate:.2f}% overall, {recent_win_rate:.2f}% recent 20.",
        f"Average edge: {avg_edge_pct:.2f}%.",
        f"Open local positions: {len(positions)}.",
    ]

    headline = "Manager review is green enough to keep iterating, but not to assume certainty."
    if goal_pct >= 100:
        headline = "Friday profit target is already met on expected P&L. Keep discipline before widening risk."
    elif estimated_pnl <= 0:
        headline = "Manager review says slow down, tighten entry quality, and protect edge before pushing turnover."

    return {
        "headline": headline,
        "scorecard": scorecard,
        "reinforcements": reinforcements,
        "coaching": coaching,
        "risks": risks,
        "goal_progress_pct": max(0.0, min(goal_pct, 100.0 if target_profit else 0.0)),
    }


def get_manager_state(trades: list[dict], positions: dict, stats: dict | None = None, kpi: dict | None = None) -> dict:
    active = load_active_profile_payload()
    pending = load_pending_profile_payload()
    live = load_live_profile_payload()
    profiles = load_profiles()
    validation = validate_profile(pending["profile"], trades)
    review = build_review(live["profile"], trades, positions, stats=stats, kpi=kpi)
    return {
        "active": active,
        "pending": pending,
        "live": live,
        "profiles": sorted(profiles.keys()),
        "diff": compute_profile_diff(active["profile"], pending["profile"]),
        "validation": validation,
        "review": review,
    }


def propose_pending_profile(text: str, name: str | None = None) -> dict:
    active = load_active_profile()
    proposed = propose_profile_from_text(text, active_profile=active, name=name)
    payload = save_pending_profile(
        {
            "name": proposed["name"],
            "proposal_text": text or "",
            "profile": proposed,
        }
    )
    return payload


def set_live_strategy_mode(mode: str) -> dict:
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode not in ALLOWED_STRATEGY_MODES:
        normalized_mode = "conservative"
    patch_pending_profile({"strategy_mode": normalized_mode})
    return load_live_profile_payload()
