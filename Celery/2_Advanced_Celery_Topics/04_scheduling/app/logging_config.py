"""Centralized logging configuration and pretty development formatting for Module 04 Scheduling.

Provides ContextVar-backed correlation ID propagation and a clean, concise
development formatter that highlights timestamps, log levels, truncated request IDs,
and domain attributes without cluttering the console with noisy HTTP headers.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

# Global context variable for cross-correlating async calls and Celery task traces
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


class RequestContextFilter(logging.Filter):
    """Injects the active request_id from ContextVar into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach truncated or full request_id to the log record."""
        req_id = getattr(record, "request_id", None) or current_request_id.get() or "-"
        record.request_id = req_id
        # Truncate request ID to 8 characters for clean console readability
        record.req_id_short = req_id[:8] if req_id != "-" else "-"
        return True


class PrettyDevFormatter(logging.Formatter):
    """Clean development log formatter for terminal and VS Code debugging.

    Formats:
    HH:MM:SS [LEVEL] [req_id[:8]] logger_name: message | key1=val1 key2=val2
    """

    # ANSI color codes for pretty terminal output
    COLOR_MAP = {
        logging.DEBUG: "\033[36m",  # Cyan
        logging.INFO: "\033[32m",  # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",  # Red
        logging.CRITICAL: "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    # Fields to exclude from extra key=value suffix to avoid redundancy
    EXCLUDED_RECORD_ATTRS = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "request_id",
        "req_id_short",
        "message",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format the specified record with truncated UUID and extra attributes."""
        # 1. Format timestamp as HH:MM:SS
        record.asctime = self.formatTime(record, datefmt="%H:%M:%S")

        # 2. Add color if supported
        color = self.COLOR_MAP.get(record.levelno, "")
        reset = self.RESET if color else ""
        level_str = f"{color}{record.levelname:<5}{reset}"

        # 3. Base message prefix: HH:MM:SS [LEVEL] [req_id[:8]] name: message
        req_id_short = getattr(record, "req_id_short", "-")
        base = f"{record.asctime} [{level_str}] [{req_id_short}] {record.name}: {record.getMessage()}"

        # 4. Extract extra keyword attributes formatted as key=value
        extras: list[str] = []
        for key, val in record.__dict__.items():
            if key not in self.EXCLUDED_RECORD_ATTRS and not key.startswith("_"):
                extras.append(f"{key}={val}")

        if extras:
            base = f"{base} | {' '.join(extras)}"

        # 5. Attach exception traceback if present
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            base = f"{base}\n{record.exc_text}"

        return base


def configure_logging(log_level: str = "INFO") -> None:
    """Configure the root and application loggers with PrettyDevFormatter.

    Args:
        log_level: Desired log level string ('DEBUG', 'INFO', 'WARNING', 'ERROR').
    """
    # 1. Determine numeric log level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # 2. Create stream handler with context filter and pretty formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(PrettyDevFormatter())

    # 3. Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    # Clear existing handlers to prevent duplicate lines
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # 4. Quiet excessively noisy third-party libraries in development
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("kombu").setLevel(logging.WARNING)
