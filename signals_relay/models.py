# signals_relay/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(slots=True)
class TradeSignal:
    symbol: str           # например, "SOLUSDT"
    side: Side            # LONG/SHORT
    entry: float
    stop: float
    take: float
    leverage: int | None = None

    @property
    def is_short(self) -> bool:
        return self.side is Side.SHORT
