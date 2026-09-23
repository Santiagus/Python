"""Unit tests for centralized logging configuration, PrettyDevFormatter, and ContextVar correlation."""

from __future__ import annotations

import logging
import sys

import pytest

from app.logging_config import (
    PrettyDevFormatter,
    RequestContextFilter,
    configure_logging,
    current_request_id,
)


@pytest.mark.unit
def test_request_context_filter_with_contextvar() -> None:
    """Verify RequestContextFilter injects truncated request_id from ContextVar."""
    filter_ = RequestContextFilter()
    token = current_request_id.set("12345678-abcd-ef01-2345-6789abcdef01")

    try:
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="test message",
            args=(),
            exc_info=None,
        )
        assert filter_.filter(record) is True
        assert record.request_id == "12345678-abcd-ef01-2345-6789abcdef01"
        assert record.req_id_short == "12345678"
        assert getattr(record, "request_id") == "12345678-abcd-ef01-2345-6789abcdef01"
        assert getattr(record, "req_id_short") == "12345678"
    finally:
        current_request_id.reset(token)


@pytest.mark.unit
def test_request_context_filter_default() -> None:
    """Verify RequestContextFilter defaults to '-' when no correlation ID exists."""
    filter_ = RequestContextFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="test message",
        args=(),
        exc_info=None,
    )
    assert filter_.filter(record) is True
    assert record.request_id == "-"
    assert record.req_id_short == "-"
    assert getattr(record, "request_id") == "-"
    assert getattr(record, "req_id_short") == "-"


@pytest.mark.unit
def test_pretty_dev_formatter_formatting() -> None:
    """Verify PrettyDevFormatter output contains timestamps, colors, and extra key=value pairs."""
    formatter = PrettyDevFormatter()
    record = logging.LogRecord(
        name="services.worker.tasks",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=25,
        msg="Task initiated",
        args=(),
        exc_info=None,
    )
    record.req_id_short = "a1b2c3d4"
    record.custom_metric = 42
    record.period_date = "2026-09-23"

    formatted = formatter.format(record)
    assert "[DEBUG]" in formatted or "DEBUG" in formatted
    assert "[a1b2c3d4]" in formatted
    assert "services.worker.tasks: Task initiated" in formatted
    assert "custom_metric=42" in formatted
    assert "period_date=2026-09-23" in formatted


@pytest.mark.unit
def test_pretty_dev_formatter_with_exception() -> None:
    """Verify PrettyDevFormatter attaches traceback when exc_info is present."""
    formatter = PrettyDevFormatter()
    try:
        raise ValueError("Simulated financial calculation fault")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="services.worker.tasks",
        level=logging.ERROR,
        pathname=__file__,
        lineno=50,
        msg="Failed execution",
        args=(),
        exc_info=exc_info,
    )
    record.req_id_short = "err12345"

    formatted = formatter.format(record)
    assert "ValueError: Simulated financial calculation fault" in formatted
    assert "[err12345]" in formatted


@pytest.mark.unit
def test_pretty_dev_formatter_with_existing_exc_text() -> None:
    """Verify PrettyDevFormatter uses existing exc_text when already populated."""
    formatter = PrettyDevFormatter()
    try:
        raise ValueError("Pre-formatted fault")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="services.worker.tasks",
        level=logging.ERROR,
        pathname=__file__,
        lineno=50,
        msg="Failed execution with cached text",
        args=(),
        exc_info=exc_info,
    )
    record.req_id_short = "errcached"
    record.exc_text = "Pre-formatted exception traceback"

    formatted = formatter.format(record)
    assert "Pre-formatted exception traceback" in formatted


@pytest.mark.unit
def test_configure_logging() -> None:
    """Verify configure_logging sets root log level and attaches PrettyDevFormatter handler."""
    configure_logging(log_level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) >= 1
    assert any(isinstance(h.formatter, PrettyDevFormatter) for h in root.handlers)

    # Re-configure to INFO
    configure_logging(log_level="INFO")
    assert root.level == logging.INFO
