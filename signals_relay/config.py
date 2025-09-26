# signals_relay/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _to_float(value: str | None, default: float) -> float:
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return default


@dataclass(frozen=True)
class Config:
    # --- Telegram ---
    BOT_TOKEN: str
    SOURCE_ID: int
    DEST_ID: int
    TELEGRAM_POLL_INTERVAL: float
    TELEGRAM_DROP_PENDING: bool

    # --- Logging ---
    LOG_LEVEL: str
    LOG_HTTP_VERBOSE: bool

    # --- Parsing / Orders ---
    ORDER_MARKET_ENTRY: bool
    ORDER_TIME_IN_FORCE: str
    ORDER_TPSL_TRIGGER: str
    RISK_USDT_PER_TRADE: float
    RISK_DEFAULT_LEVERAGE: int

    # --- Bybit ---
    BYBIT_API_KEY: str
    BYBIT_API_SECRET: str
    BYBIT_TESTNET: bool
    BYBIT_CATEGORY: str
    BYBIT_RECV_WINDOW_MS: int
    BYBIT_MAX_RETRIES: int
    BYBIT_TIME_SYNC: bool
    BYBIT_TIME_RESYNC_SEC: int
    BYBIT_SWITCH_ISOLATED: bool
    BYBIT_TIMEOUT_SEC: float        # <— ДОБАВЛЕНО

    # --- Monitor ---
    MONITOR_POLL_SEC: float
    MONITOR_TIMEOUT_SEC: float

    # --- Helpers ---
    def is_ready(self) -> bool:
        return bool(self.BOT_TOKEN and self.SOURCE_ID and self.DEST_ID)

    @property
    def TELEGRAM_ALLOWED_UPDATES(self) -> list[str]:
        return ["message", "channel_post", "edited_channel_post"]


def _load_env() -> Config:
    load_dotenv()

    # Telegram
    bot_token = (os.getenv("BOT_TOKEN") or "").strip()
    src = os.getenv("SOURCE_ID") or os.getenv("SOURCE_CHANNEL_ID") or ""
    dst = os.getenv("DEST_ID") or os.getenv("DEST_CHAT_ID") or os.getenv("DEST_CHANNEL_ID") or ""
    source_id = _to_int(src, 0)
    dest_id = _to_int(dst, 0)
    poll_interval = _to_float(os.getenv("TELEGRAM_POLL_INTERVAL"), 1.5)
    drop_pending = _to_bool(os.getenv("TELEGRAM_DROP_PENDING"), True)

    # Logging
    log_level = (os.getenv("LOG_LEVEL") or "INFO").upper()
    log_http = _to_bool(os.getenv("LOG_HTTP_VERBOSE"), False)

    # Orders / Risk
    market_entry = _to_bool(os.getenv("ORDER_MARKET_ENTRY"), False)
    tif = (os.getenv("ORDER_TIME_IN_FORCE") or "GTC").upper()
    tpsl_trigger = (os.getenv("ORDER_TPSL_TRIGGER") or "MarkPrice")
    usdt_per_trade = _to_float(os.getenv("RISK_USDT_PER_TRADE"), 100.0)
    default_leverage = _to_int(os.getenv("RISK_DEFAULT_LEVERAGE"), 20)

    # Bybit
    bybit_key = (os.getenv("BYBIT_API_KEY") or "").strip()
    bybit_secret = (os.getenv("BYBIT_API_SECRET") or "").strip()
    bybit_testnet = _to_bool(os.getenv("BYBIT_TESTNET"), True)
    bybit_category = (os.getenv("BYBIT_CATEGORY") or "linear").lower()
    bybit_recv = _to_int(os.getenv("BYBIT_RECV_WINDOW_MS"), 5000)
    bybit_retries = _to_int(os.getenv("BYBIT_MAX_RETRIES"), 3)
    bybit_time_sync = _to_bool(os.getenv("BYBIT_TIME_SYNC"), True)
    bybit_time_resync = _to_int(os.getenv("BYBIT_TIME_RESYNC_SEC"), 60)
    bybit_switch_isolated = _to_bool(os.getenv("BYBIT_SWITCH_ISOLATED"), False)
    bybit_timeout_sec = _to_float(os.getenv("BYBIT_TIMEOUT_SEC"), 10.0)  # <— ДОБАВЛЕНО

    # Monitor
    monitor_poll = _to_float(os.getenv("MONITOR_POLL_SEC"), 2.0)
    monitor_timeout = _to_float(os.getenv("MONITOR_TIMEOUT_SEC"), 0.0)

    return Config(
        BOT_TOKEN=bot_token,
        SOURCE_ID=source_id,
        DEST_ID=dest_id,
        TELEGRAM_POLL_INTERVAL=poll_interval,
        TELEGRAM_DROP_PENDING=drop_pending,
        LOG_LEVEL=log_level,
        LOG_HTTP_VERBOSE=log_http,
        ORDER_MARKET_ENTRY=market_entry,
        ORDER_TIME_IN_FORCE=tif,
        ORDER_TPSL_TRIGGER=tpsl_trigger,
        RISK_USDT_PER_TRADE=usdt_per_trade,
        RISK_DEFAULT_LEVERAGE=default_leverage,
        BYBIT_API_KEY=bybit_key,
        BYBIT_API_SECRET=bybit_secret,
        BYBIT_TESTNET=bybit_testnet,
        BYBIT_CATEGORY=bybit_category,
        BYBIT_RECV_WINDOW_MS=bybit_recv,
        BYBIT_MAX_RETRIES=bybit_retries,
        BYBIT_TIME_SYNC=bybit_time_sync,
        BYBIT_TIME_RESYNC_SEC=bybit_time_resync,
        BYBIT_SWITCH_ISOLATED=bybit_switch_isolated,
        BYBIT_TIMEOUT_SEC=bybit_timeout_sec,  # <— ДОБАВЛЕНО
        MONITOR_POLL_SEC=monitor_poll,
        MONITOR_TIMEOUT_SEC=monitor_timeout,
    )


cfg = _load_env()

if not cfg.is_ready():
    raise SystemExit("✖ BOT_TOKEN / SOURCE_ID / DEST_ID не заданы в .env")
