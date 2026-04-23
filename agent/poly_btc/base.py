"""Base dataclasses and abstract strategy interface for the poly_btc pack."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategyConfig:
    enabled: bool = True
    # Time window (seconds remaining in market)
    seconds_remaining_min: float = 0.0
    seconds_remaining_max: float = 172800.0   # 48h
    # Order routing
    entry_order_type: str = "FOK"             # FOK | FAK | LIMIT
    exit_order_type: str = "FOK"
    entry_tif: str = "IOC"                    # IOC | GTC | FOK
    exit_tif: str = "IOC"
    # Risk per position
    stop_loss_pct: float = 0.08
    profit_take_pct: float = 0.12
    # Entry gates
    max_entry_price: float = 0.88             # won't buy above this (near-resolved market)
    max_spread_pct: float = 0.18
    max_size_usdc: float = 5.0
    # Behaviour
    cooldown_seconds: int = 300
    confirmation_ticks: int = 0               # extra ticks before committing
    allow_taker: bool = True
    allow_limit: bool = True
    min_edge: float = 0.04


@dataclass
class BTCOpportunity:
    market_id: str
    question: str
    token_id: str
    side: str                                 # YES | NO
    strategy: str                             # strategy name
    edge: float
    price: float                              # market price for this side
    our_prob: float
    size_usdc: float
    order_type: str
    tif: str
    market_state: str
    seconds_to_expiry: float
    confidence: str                           # HIGH | MEDIUM | LOW
    sym: str = "BTC_PACK"


class BaseStrategy(ABC):
    name: str = "base"

    def __init__(self, config: StrategyConfig):
        self.config = config
        self._cooldowns: dict[str, float] = {}   # market_id → last_entry_ts

    # ---------------------------------------------------------------- cooldown
    def in_cooldown(self, market_id: str) -> bool:
        last = self._cooldowns.get(market_id)
        if last is None:
            return False
        return (time.time() - last) < self.config.cooldown_seconds

    def record_entry(self, market_id: str):
        self._cooldowns[market_id] = time.time()

    # ----------------------------------------------------------- time / state
    def should_activate(self, market_state: str, seconds_to_expiry: float) -> bool:
        if not self.config.enabled:
            return False
        if seconds_to_expiry < self.config.seconds_remaining_min:
            return False
        if seconds_to_expiry > self.config.seconds_remaining_max:
            return False
        return True

    # ------------------------------------------------------------------ score
    @abstractmethod
    def score(
        self,
        market: dict,
        btc_price: float,
        candle_analysis: dict,
        market_state_obj,
    ) -> Optional[BTCOpportunity]:
        """
        Return a BTCOpportunity if this market meets entry criteria, else None.
        Do NOT check cooldowns or spread here — the registry handles those gates.
        """
        ...
