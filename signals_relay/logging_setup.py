# signals_relay/logging_setup.py
import logging
import os

from .config import Config


def setup_logging(cfg: Config) -> None:
    # базовый формат
    logging.basicConfig(
        level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # подробные HTTP-логи по желанию
    if cfg.LOG_HTTP_VERBOSE:
        # httpx
        logging.getLogger("httpx").setLevel(logging.DEBUG)
        logging.getLogger("httpcore").setLevel(logging.DEBUG)
        # telegram
        logging.getLogger("telegram.request").setLevel(logging.DEBUG)
    else:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("telegram.request").setLevel(logging.INFO)

    logging.info("Logging ready: level=%s, http_verbose=%s", cfg.LOG_LEVEL, cfg.LOG_HTTP_VERBOSE)
