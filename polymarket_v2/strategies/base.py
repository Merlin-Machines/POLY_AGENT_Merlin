from abc import ABC, abstractmethod
from typing import Iterable

from polymarket_v2.domain.models import Market, Opportunity


class Strategy(ABC):
    strategy_id: str

    @abstractmethod
    def find_opportunities(self, markets: Iterable[Market]) -> list[Opportunity]:
        raise NotImplementedError
