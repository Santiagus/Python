"""Runtime logging configuration for structured and human-readable request logging."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

# Context variable to track current request ID across async tasks
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)

# Standard LogRecord attributes to ignore when extracting extras
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class RequestContextFilter(logging.Filter):
    """Inject current request ID from async context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if (req_id := current_request_id.get()) and not hasattr(record, "request_id"):
            record.request_id = req_id
        return True


class PrettyFormatter(logging.Formatter):
    """Compact, human-readable log formatter for development."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")}

        # 1. Shorten request ID (8 chars) if present
        req_id = str(extras.pop("request_id", ""))[:8]

        # 2. Extract HTTP metrics if present (omit 'ms' if duration missing)
        http = [str(extras.pop(k)) for k in ("method", "path", "status_code") if extras.get(k)]
        if dur := extras.pop("duration_ms", None):
            http.append(f"{dur}ms")

        # 3. Format any remaining domain extra dictionary items
        domain = [f"{k}={v!r}" if " " in str(v) else f"{k}={v}" for k, v in extras.items() if v is not None]

        parts = ([req_id] if req_id else []) + http + domain
        base = super().format(record)
        if parts:
            first, *rest = base.split("\n", 1)
            return f"{first} {' '.join(parts)}" + (f"\n{rest[0]}" if rest else "")
        return base


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    """Configure the root logger to emit JSON or human-readable pretty request logs."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        PrettyFormatter()
        if log_format.lower() == "pretty"
        else JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "level", "asctime": "timestamp"},
        )
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
