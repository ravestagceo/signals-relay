import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from .config import Config
from .parser import parse_signal, render_normalized
from .utils import first_line, snippet, cfg_mode_str
from .bus import SignalBus
from .broker.bybit import BybitBroker

# helpers to get shared objects from app.bot_data
def _cfg(ctx: ContextTypes.DEFAULT_TYPE) -> Config:
    return ctx.application.bot_data["cfg"]

def _bus(ctx: ContextTypes.DEFAULT_TYPE) -> SignalBus:
    return ctx.application.bot_data["bus"]

def _broker(ctx: ContextTypes.DEFAULT_TYPE):
    
    return ctx.application.bot_data.get("broker")

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = _cfg(context)
    msg  = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or chat.id != cfg.SOURCE_ID:
        return

    text = msg.text or msg.caption or ""
    logging.info(f"channel_post mid={msg.message_id} first='{first_line(text, cfg.LOG_SNIPPET_LEN)}'")

    sig = parse_signal(text, msg.message_id, chat.id)
    if not sig:
        logging.info("[SKIP] not a trade signal (missing fields)")
        return

    logging.info(
        f"[PARSED] {sig.symbol} {sig.side.upper()} "
        f"entry={sig.entry_s} stop={sig.stop_s} take={sig.take_s} lev=x{sig.leverage}"
    )

    # публикуем нормализованный вид
    try:
        norm = render_normalized(sig)
        await context.bot.send_message(cfg.DEST_ID, norm, disable_web_page_preview=True)
        logging.info(f"[OK] Sent normalized signal for post {msg.message_id}")
    except Exception as e:
        logging.warning(f"[WARN] send normalized failed: {e}")

    # в очередь брокеру
    _bus(context).enqueue_if_new(sig)

async def on_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = _cfg(context)
    if not cfg.VERBOSE_UPDATES:
        return
    msg = update.effective_message
    if not msg:
        return
    text = msg.text or msg.caption or ""
    logging.info(
        f"update: chat={msg.chat.id} type={msg.chat.type} mid={getattr(msg, 'message_id', '-')}"
        f" text='{snippet(text, cfg.LOG_SNIPPET_LEN)}'"
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.warning(f"[NET] {type(context.error).__name__}: {context.error}")
    await asyncio.sleep(1.0)

async def post_init(app):
    cfg: Config = app.bot_data["cfg"]
    bus: SignalBus = app.bot_data["bus"]

    # брокер
    broker = None
    if cfg.BROKER == "BYBIT":
        broker = BybitBroker(cfg)
    else:
        logging.warning(f"Неизвестный брокер {cfg.BROKER} — работаем без торговых операций.")
    app.bot_data["broker"] = broker

    # старт воркера очереди
    asyncio.create_task(bus.worker(broker))

    me = await app.bot.get_me()
    logging.info(f"Logged in as @{me.username} ({me.id})")

    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook cleared.")
    except Exception as e:
        logging.info(f"delete_webhook: {e}")

    try:
        await app.bot.send_message(cfg.DEST_ID, "✅ Relay online (startup test)")
        logging.info("Startup test message sent to DEST.")
    except Exception as e:
        logging.error(f"✖ Cannot send to DEST ({cfg.DEST_ID}): {e}")

    # роли
    try:
        m = await app.bot.get_chat_member(cfg.SOURCE_ID, me.id)
        logging.info(f"Source role: {m.status}")
        if m.status not in ("administrator", "creator"):
            logging.error("✖ Бот НЕ админ источника — в канале нужно дать админ-права.")
    except Exception as e:
        logging.error(f"✖ Не удалось проверить SOURCE: {e}")

    try:
        m = await app.bot.get_chat_member(cfg.DEST_ID, me.id)
        logging.info(f"Dest role: {m.status}")
    except Exception as e:
        logging.error(f"✖ Не удалось проверить DEST: {e}")
