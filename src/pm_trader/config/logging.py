from __future__ import annotations

import logging
import sys

import structlog

from pm_trader.config.settings import AppSettings


def configure_logging(settings: AppSettings | None = None) -> None:
    """Configure structured JSON logging for application code."""
    active_settings = settings or AppSettings()
    level = getattr(logging, active_settings.log_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stderr,
        force=True,
    )
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    structlog.configure(
        cache_logger_on_first_use=True,
        logger_factory=structlog.stdlib.LoggerFactory(),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structured logger."""
    return structlog.get_logger(name)
