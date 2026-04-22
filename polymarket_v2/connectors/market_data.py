from typing import Iterable, Protocol

from polymarket_v2.domain.models import Market


class MarketDataProvider(Protocol):
    def fetch_markets(self) -> Iterable[Market]:
        ...
