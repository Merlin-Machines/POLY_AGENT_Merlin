"""
agent/poly_btc — BTC strategy pack for POLY_AGENT_Merlin.

Usage (from main.py):
    from agent.poly_btc import PolyBTCRegistry
    registry = PolyBTCRegistry(data_dir)
    registry.set_executor(executor)          # after executor is ready
    opps = registry.scan(btc_markets, ...)   # called each cycle
"""

from agent.poly_btc.registry import PolyBTCRegistry

__all__ = ["PolyBTCRegistry"]
