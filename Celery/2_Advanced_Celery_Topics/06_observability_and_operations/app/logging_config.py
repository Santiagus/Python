"""Development logging configuration with context-aware pretty formatter.

Provides ContextVar-backed correlation ID propagation and formatted console logs.
"""

import logging
import sys
from contextvars import ContextVar

current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


class DevelopmentLogFormatter(logging.Formatter):
    """Pretty development log formatter with short timestamps and truncated UUIDs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with truncated request correlation context.

        Args:
            record: Standard Python LogRecord instance.

        Returns:
            str: Pretty formatted log line string.
        """
        # 1. Format time with short time specification
        record.asctime = self.formatTime(record, "%H:%M:%S")

        # 2. Extract and format correlation ID
        req_id = current_request_id.get() or getattr(record, "request_id", None)
        req_prefix = f"[{req_id[:8]}] " if req_id else ""

        # 3. Format extra attributes concisely
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "request_id",
        }
        extras = [
            f"{k}={v}"
            for k, v in record.__dict__.items()
            if k not in standard_attrs and not k.startswith("_")
        ]
        extras_str = f" ({', '.join(extras)})" if extras else ""

        # 4. Construct human-readable development line
        msg = record.getMessage()
        return (
            f"{record.asctime} {record.levelname:5s} {req_prefix}{record.name}: {msg}{extras_str}"
        )


def setup_logging(log_level: str = "INFO") -> None:
    """Initialize development logger with standard formatters and handlers.

    Args:
        log_level: Desired minimum logging severity level.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 1. Clear existing handlers to prevent duplicate lines
    root_logger.handlers.clear()

    # 2. Attach stdout stream handler with development formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(DevelopmentLogFormatter(datefmt="%H:%M:%S"))
    root_logger.addHandler(handler)
