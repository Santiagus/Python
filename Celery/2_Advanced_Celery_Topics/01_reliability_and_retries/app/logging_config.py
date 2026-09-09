"""Runtime logging configuration used for structured request logging."""

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def configure_logging(level: str, log_format: str = "json") -> None:
    """Configure the root logger to emit JSON or human-readable request logs."""
    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "pretty":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s "
                "%(request_id)s %(method)s %(path)s "
                "%(status_code)s %(duration_ms)sms",
                defaults={
                    "request_id": "-",
                    "method": "-",
                    "path": "-",
                    "status_code": "-",
                    "duration_ms": "-",
                },
            )
        )
    else:
        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"levelname": "level", "asctime": "timestamp"},
            )
        )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
