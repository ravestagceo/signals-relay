# signals_relay/broker/base.py
from abc import ABC, abstractmethod

from ..models import TradeSignal


class BrokerBase(ABC):
    @abstractmethod
    async def place_trade(self, sig: TradeSignal):
        ...
