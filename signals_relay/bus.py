# signals_relay/bus.py
import asyncio
import contextlib
import logging
from typing import Optional

from signals_relay.config import cfg
from signals_relay.models import TradeSignal
from signals_relay.broker.bybit import BybitBroker

log = logging.getLogger(__name__)


class TradingBus:
    """
    Очередь → воркер. Принимает нормализованные сигналы, готовит символ, считает qty и
    отправляет заявку на биржу. Ошибки брокера не обваливают воркер.
    """

    def __init__(
        self,
        broker: BybitBroker,
        *,
        usdt_per_trade: float | None = None,
        default_leverage: int | None = None,
        market_entry: bool | None = None,
        max_concurrent: int = 1,
    ) -> None:
        self.broker = broker
        self.q: asyncio.Queue[TradeSignal] = asyncio.Queue()
        self.sem = asyncio.Semaphore(max_concurrent)

        self.usdt_per_trade = usdt_per_trade if usdt_per_trade is not None else cfg.RISK_USDT_PER_TRADE
        self.default_leverage = default_leverage if default_leverage is not None else cfg.RISK_DEFAULT_LEVERAGE
        self.market_entry = market_entry if market_entry is not None else cfg.ORDER_MARKET_ENTRY

        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._worker(), name="trading-bus")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def enqueue(self, s: TradeSignal) -> None:
        await self.q.put(s)
        log.info("[BUS] enqueued")
        log.info(
            "[BUS] %s %s entry=%s stop=%s take=%s lev=%s",
            s.symbol, s.side.name, s.entry, s.stop, s.take, s.leverage or "x?",
        )

    async def _worker(self) -> None:
        while True:
            s = await self.q.get()
            try:
                await self._handle_signal(s)
            except Exception as e:
                log.error("[BUS] broker error: %s", e)
            finally:
                self.q.task_done()

    # ---------- core ----------

    async def _handle_signal(self, s: TradeSignal) -> None:
        async with self.sem:
            symbol = s.symbol
            lev = s.leverage or self.default_leverage
            side = "Sell" if s.is_short else "Buy"
            order_type = "Market" if self.market_entry else "Limit"

            # подготовка аккаунта (best-effort)
            try:
                await self.broker.set_leverage(symbol, lev)
            except Exception as e:
                log.warning("Bybit: set_leverage failed: %s", e)

            if cfg.BYBIT_SWITCH_ISOLATED:
                try:
                    await self.broker.switch_isolated(symbol)
                except Exception as e:
                    log.warning("Bybit: switch_isolated failed: %s", e)

            # капитал → количество
            qty = await self._calc_qty(symbol, s.entry, lev)

            # округления под шаги инструмента
            price_q, qty_q = await self.broker.quantize_price_qty(
                symbol, (None if order_type == "Market" else s.entry), qty
            )
            tp_q, _ = await self.broker.quantize_price_qty(symbol, s.take, qty_q)
            sl_q, _ = await self.broker.quantize_price_qty(symbol, s.stop, qty_q)

            log.info(
                "[BROKER] Bybit %s %s qty=%s price=%s sl=%s tp=%s lev=x%s tif=%s market_entry=%s",
                symbol,
                side,
                qty_q,
                price_q if price_q is not None else "MARKET",
                sl_q,
                tp_q,
                lev,
                cfg.ORDER_TIME_IN_FORCE,
                order_type == "Market",
            )

            res = await self.broker.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                qty=qty_q,
                price=price_q,
                take_profit=tp_q,
                stop_loss=sl_q,
                time_in_force=cfg.ORDER_TIME_IN_FORCE,
                reduce_only=False,
                tpsl_mode="Full",
                trigger_by=cfg.ORDER_TPSL_TRIGGER,
            )
            order_id = (res or {}).get("orderId")
            log.info("[BUS] order accepted: %s", order_id)

    async def _calc_qty(self, symbol: str, entry: float, leverage: int) -> float:
        nominal = self.usdt_per_trade * leverage
        return nominal / max(entry, 1e-9)
