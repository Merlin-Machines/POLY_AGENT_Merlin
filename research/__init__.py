"""
research/ — Silver-Fox-derived offline tooling for the Merlin Polymarket agent.

This package adds backtesting, hyperparameter optimization, disciplined risk
management, and an ML training pipeline. All of it is OFFLINE and never touches
the live runtime — import it only from scripts and notebooks.

Key adaptation vs. Silver-Fox (which traded spot BTC):
  • P&L is modelled as BINARY Polymarket contract economics, not spot buy/sell.
  • ATR is used as a volatility-sizing / veto input, NOT as a token exit price.
  • Features and the FEATURE_COLS contract are reused from utils.indicators so a
    model trained here is directly loadable by utils.ml_filter.MLFilter at runtime.
"""
import sys as _sys

# Windows consoles default to cp1252 and mangle the box/dash glyphs the research
# scripts print. Force UTF-8 once, at import time, for every research entrypoint.
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

