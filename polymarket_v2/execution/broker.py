from abc import ABC, abstractmethod

from polymarket_v2.domain.models import Opportunity


class Broker(ABC):
    @abstractmethod
    def place(self, opportunity: Opportunity) -> str:
        raise NotImplementedError
