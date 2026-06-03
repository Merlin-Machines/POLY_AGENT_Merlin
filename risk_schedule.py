"""
risk_schedule.py — time + P&L based aggressive -> balanced auto-revert.

Window rule (agreed during MGMT planning):
  • First 3 hours of a live session  -> AGGRESSIVE limits.
  • After 3h:
        if the session has made profit -> latch to BALANCED (lock the win in).
        if still no profit             -> stay AGGRESSIVE to give it room.
  • Hard cap at 3 days                 -> latch to BALANCED no matter what.
  • Once reverted it stays balanced (no re-aggro). State is persisted to
    data/risk_window.json so a restart resumes the same window.

This module ONLY adjusts risk limits on the live CFG object. It never places,
sizes, cancels, or resolves a trade — execution stays entirely with the agent.

Profit signal used: executor same-day realized P&L + open unrealized P&L. The
3-hour decision (the important one) is well inside a single UTC day so it is
exact; across the 3-day extension a midnight reset can undercount realized P&L,
which only errs toward staying aggressive longer. Tune below if you want stricter.
"""
from __future__ import annotations

import json
import os
import time

# ── Tunables ──────────────────────────────────────────────────────────────────
AGGRESSIVE_HOURS = 3.0      # always aggressive for this long
HARD_CAP_DAYS = 3.0         # force balanced after this long, unconditionally
PROFIT_EPS = 0.0            # realized+unrealized must exceed this to lock in

STATE_PATH = os.path.join("data", "risk_window.json")

# Aggressive = the current live config values (kept as-is per your instruction).
AGGRESSIVE_LIMITS = {
    "max_trade_usdc": 4.0,
    "min_trade_usdc": 0.80,
    "min_liquidity": 200.0,
    "max_open_positions": 10,
    "max_daily_loss": 30.0,
    "max_daily_trades": 50,
    "kelly_fraction": 0.25,
    "min_edge": 0.02,
}
# Balanced = roughly half the risk surface for when the window closes.
BALANCED_LIMITS = {
    "max_trade_usdc": 2.0,
    "min_trade_usdc": 0.80,
    "min_liquidity": 400.0,
    "max_open_positions": 5,
    "max_daily_loss": 15.0,
    "max_daily_trades": 20,
    "kelly_fraction": 0.15,
    "min_edge": 0.03,
}


def _load_state() -> dict | None:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def decide_posture(now_ts: float, realized_pnl: float, state: dict | None) -> tuple[str, dict, str]:
    """Pure decision function. Returns (posture, new_state, reason)."""
    if state is None:
        state = {"start_ts": now_ts, "reverted": False}
    if state.get("reverted"):
        return "balanced", state, "latched_balanced"

    elapsed_h = (now_ts - state["start_ts"]) / 3600.0
    if elapsed_h < AGGRESSIVE_HOURS:
        return "aggressive", state, f"warmup {elapsed_h:.2f}h<{AGGRESSIVE_HOURS:.0f}h"

    if elapsed_h >= HARD_CAP_DAYS * 24:
        state["reverted"] = True
        return "balanced", state, f"hard_cap {HARD_CAP_DAYS:.0f}d reached"

    if realized_pnl > PROFIT_EPS:
        state["reverted"] = True
        return "balanced", state, f"profit_locked pnl={realized_pnl:+.2f}"

    return "aggressive", state, f"no_profit_extend pnl={realized_pnl:+.2f} elapsed={elapsed_h:.1f}h"


def apply_to_config(cfg, posture: str) -> dict:
    """Mutate cfg's risk limits in place to match the posture."""
    limits = AGGRESSIVE_LIMITS if posture == "aggressive" else BALANCED_LIMITS
    for key, val in limits.items():
        if hasattr(cfg, key):
            setattr(cfg, key, val)
    return limits


def tick(cfg, realized_pnl: float, now_ts: float | None = None) -> tuple[str, str, bool]:
    """
    Call once per cycle. Mutates cfg limits in place and persists window state.
    Returns (posture, reason, changed).
    """
    now_ts = time.time() if now_ts is None else now_ts
    state = _load_state()
    prev = state.get("posture") if state else None
    posture, state, reason = decide_posture(now_ts, realized_pnl, state)
    apply_to_config(cfg, posture)
    state["posture"] = posture
    state["last_pnl"] = round(float(realized_pnl), 4)
    state["last_ts"] = now_ts
    _save_state(state)
    return posture, reason, (prev != posture)


def reset_window(now_ts: float | None = None) -> None:
    """Start a fresh aggressive window (e.g. at the start of a new live session)."""
    _save_state({"start_ts": time.time() if now_ts is None else now_ts, "reverted": False})
