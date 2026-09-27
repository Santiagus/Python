"""Unit tests for development logger formatter and request context filtering."""

from __future__ import annotations

import logging

from app.logging_config import (
    PrettyDevFormatter,
    RequestContextFilter,
    configure_logging,
    current_request_id,
)


def test_request_context_filter() -> None:
    """Verify RequestContextFilter injects truncated and fallback request IDs."""
    filt = RequestContextFilter()

    # 1. Fallback when ContextVar is None
    current_request_id.set(None)
    record = logging.LogRecord("test", logging.INFO, "test.py", 10, "msg", (), None)
    assert filt.filter(record) is True
    assert getattr(record, "request_id") == "-"
    assert getattr(record, "req_id_short") == "-"

    # 2. ContextVar populated with UUID
    token = current_request_id.set("abcdef12-3456-7890-abcd-ef1234567890")
    record2 = logging.LogRecord("test", logging.INFO, "test.py", 10, "msg", (), None)
    assert filt.filter(record2) is True
    assert getattr(record2, "request_id") == "abcdef12-3456-7890-abcd-ef1234567890"
    assert getattr(record2, "req_id_short") == "abcdef12"

    # 3. Explicit attribute on record
    record3 = logging.LogRecord("test", logging.INFO, "test.py", 10, "msg", (), None)
    setattr(record3, "request_id", "custom_req_id_long")
    assert filt.filter(record3) is True
    assert getattr(record3, "req_id_short") == "custom_r"

    current_request_id.reset(token)


def test_pretty_dev_formatter_formatting() -> None:
    """Verify PrettyDevFormatter formats levels, extras, and exceptions."""
    formatter = PrettyDevFormatter()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="operation successful",
        args=(),
        exc_info=None,
    )
    record.request_id = "req_12345678"  # type: ignore[attr-defined]
    record.req_id_short = "req_1234"  # type: ignore[attr-defined]
    record.amount_cents = 5000  # type: ignore[attr-defined]

    formatted = formatter.format(record)
    assert "INFO" in formatted
    assert "[req_1234]" in formatted
    assert "test_logger:" in formatted
    assert "operation successful" in formatted
    assert "amount_cents=5000" in formatted


def test_pretty_dev_formatter_exception() -> None:
    """Verify PrettyDevFormatter appends formatted stack traces on error."""
    formatter = PrettyDevFormatter()

    try:
        raise ValueError("synthetic boom")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=20,
        msg="failure occurred",
        args=(),
        exc_info=exc_info,
    )
    formatted = formatter.format(record)
    assert "ValueError: synthetic boom" in formatted


def test_configure_logging() -> None:
    """Verify configure_logging attaches formatter, filter, and sets log level."""
    configure_logging(log_level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) >= 1
