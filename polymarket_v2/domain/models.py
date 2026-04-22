from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    YES = "YES"
    NO = "NO"


@dataclass(frozen=True)
class Market:
    market_id: str
    question: str
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    liquidity: float
    hours_to_expiry: float
    symbol: str


@dataclass(frozen=True)
class Opportunity:
    market_id: str
    side: Side
    edge: float
    market_price: float
    token_id: str
    size_usd: float
    strategy_id: str
    confidence: str
    reason: str


@dataclass
class Position:
    market_id: str
    side: Side
    entry_price: float
    size_usd: float
    opened_at: datetime
    strategy_id: str
    status: str = "open"
