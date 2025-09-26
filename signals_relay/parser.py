import logging
import re
from typing import Optional

from .models import TradeSignal, Side
from .utils import normalize_number

log = logging.getLogger(__name__)

# позволяем пробелы и юникод-пробелы внутри числа: 112 043, 112 043, 1 234,56 и т.п.
NUM = r"[0-9][0-9\s.,\u00A0\u2009\u202F]*"

RE_SYMBOL = re.compile(r"\$?\s*([A-Z]{2,10}USDT)\b")
RE_SIDE   = re.compile(r"\b(шорт|short|sell|лонг|long|buy)\b", re.IGNORECASE)
RE_ENTRY  = re.compile(r"(?:вход|entry)\s*[-:–]\s*(" + NUM + ")", re.IGNORECASE)
RE_STOP   = re.compile(r"(?:cтоп|стоп|stop|sl)\s*[-:–]\s*(" + NUM + ")", re.IGNORECASE)
RE_TAKE   = re.compile(r"(?:тейк|take|tp)\s*[-:–]\s*(" + NUM + ")", re.IGNORECASE)
RE_LEV    = re.compile(r"(?:плечо|lev|leverage)\s*[-:–]?\s*x?(\d+)", re.IGNORECASE)


def parse_signal(text: str) -> Optional[TradeSignal]:
    if not text:
        return None

    # схлопнем переносы, лишние пробелы между блоками, но сами числовые пробелы допустимы
    t = " ".join(line.strip() for line in text.splitlines() if line.strip())

    m_sym = RE_SYMBOL.search(t)
    m_side = RE_SIDE.search(t)
    m_en = RE_ENTRY.search(t)
    m_st = RE_STOP.search(t)
    m_tp = RE_TAKE.search(t)

    if not (m_sym and m_side and m_en and m_st and m_tp):
        return None

    symbol = m_sym.group(1).upper()

    side_raw = m_side.group(1).lower()
    side = Side.SHORT if side_raw in {"шорт", "short", "sell"} else Side.LONG

    entry = normalize_number(m_en.group(1))
    stop  = normalize_number(m_st.group(1))
    take  = normalize_number(m_tp.group(1))

    m_lev = RE_LEV.search(t)
    lev = int(m_lev.group(1)) if m_lev else None

    return TradeSignal(symbol=symbol, side=side, entry=entry, stop=stop, take=take, leverage=lev)


def pretty_signal(sig: TradeSignal) -> str:
    return (f"{sig.symbol}\n"
            f"{'SHORT' if sig.is_short else 'LONG'}\n"
            f"entry={sig.entry}\nstop={sig.stop}\ntake={sig.take}\n"
            f"lev={'x'+str(sig.leverage) if sig.leverage else '—'}")
