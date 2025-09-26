# signals_relay/telegram_app.py
# signals_relay/telegram_app.py
import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
from telegram.request import HTTPXRequest

from .config import cfg
from .logging_setup import setup_logging
from .parser import parse_signal, pretty_signal
from .broker.bybit import BybitBroker
from .bus import TradingBus

log = logging.getLogger(__name__)

# Глобальные синглтоны на время жизни приложения
_broker: Optional[BybitBroker] = None
_bus: Optional[TradingBus] = None


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return

    first = (msg.text or msg.caption or "").strip().splitlines()[0] if (msg.text or msg.caption) else ""
    log.info("channel_post mid=%s first='%s'", msg.message_id, first[:30])

    # фильтр по источнику
    if chat.id != cfg.SOURCE_ID:
        return

    # текст сообщения
    text = msg.text or msg.caption or ""
    sig = parse_signal(text)
    if not sig:
        log.info("[SKIP] not a trade signal (missing fields)")
        return

    # отправить нормализованный сигнал в DEST
    pretty = pretty_signal(sig)
    await context.bot.send_message(cfg.DEST_ID, pretty, disable_web_page_preview=True)
    log.info("[OK] Sent normalized signal for post %s", msg.message_id)

    # enqueue → трейдинг-воркер
    if _bus:
        await _bus.enqueue(sig)


async def on_any_update(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    # короткий диагностический лог: тип чата и первая строка текста
    msg = update.effective_message
    if not msg:
        return
    chat = msg.chat
    text = (msg.text or msg.caption or "").strip()
    first = text.splitlines()[0] if text else ""
    log.info("update: chat=%s type=%s first='%s'", chat.id, chat.type, first[:40])


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.warning("[ERR] %s: %s", type(context.error).__name__, context.error)
    await asyncio.sleep(0.5)


async def post_init(app: Application) -> None:
    """Этот хук вызывается уже внутри event loop PTB (v20), здесь инициализируем брокер/шину."""
    global _broker, _bus

    # брокер и шина
    _broker = BybitBroker()           # логирует: Broker=Bybit v5 ready [...]
    _bus = TradingBus(_broker)
    await _bus.start()                # стартуем воркер очереди в текущем loop

    me = await app.bot.get_me()

    # Сброс вебхука
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook cleared.")
    except Exception as e:
        log.info("delete_webhook: %s", e)

    # Тест: можем ли писать в DEST
    try:
        await app.bot.send_message(cfg.DEST_ID, "✅ Relay online (startup test)")
        log.info("Startup test message sent to DEST.")
    except Exception as e:
        log.error("✖ Cannot send to DEST (%s): %s", cfg.DEST_ID, e)

    # Проверка ролей
    try:
        m = await app.bot.get_chat_member(cfg.SOURCE_ID, me.id)
        log.info("Source role: %s", m.status)
    except Exception as e:
        log.error("✖ Не удалось проверить SOURCE: %s", e)

    try:
        m = await app.bot.get_chat_member(cfg.DEST_ID, me.id)
        log.info("Dest role: %s", m.status)
    except Exception as e:
        log.error("✖ Не удалось проверить DEST: %s", e)

    log.info("Application started")


def run_app() -> None:
    """Вариант для PTB v20: никакого asyncio.run — PTB сам запустит/закроет loop внутри run_polling()."""
    setup_logging(cfg)
    log.info("Relay running. Source: %s → Dest: %s", cfg.SOURCE_ID, cfg.DEST_ID)

    # HTTPX таймауты для Telegram
    request = HTTPXRequest(
        connect_timeout=15.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=15.0,
    )

    app = (
        Application.builder()
        .token(cfg.BOT_TOKEN)
        .request(request)
        .post_init(post_init)      # наш хук инициализирует брокер/шину и делает проверки
        .build()
    )

    # хендлеры
    app.add_handler(MessageHandler(filters.ALL, on_any_update), group=0)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post), group=1)
    app.add_error_handler(error_handler)

    # ВАЖНО: для v20 это синхронный вызов (блокирует поток) и сам управляет event loop
    app.run_polling(
        allowed_updates=cfg.TELEGRAM_ALLOWED_UPDATES,
        drop_pending_updates=cfg.TELEGRAM_DROP_PENDING,
        poll_interval=cfg.TELEGRAM_POLL_INTERVAL,
    )
