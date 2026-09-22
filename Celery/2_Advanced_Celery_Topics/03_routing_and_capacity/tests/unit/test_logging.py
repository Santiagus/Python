"""Unit tests for development pretty logger and distributed tracing context."""

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
class TestLoggingConfig:
    """Test PrettyDevFormatter formatting, ContextVar extraction, and logger initialization."""

    def test_request_context_filter_with_and_without_contextvar(self) -> None:
        """Filter attaches request_id and req_id_short correctly."""
        filter_obj = RequestContextFilter()
        rec1 = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="t.py",
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )

        # Without contextvar
        filter_obj.filter(rec1)
        assert rec1.request_id == "-"
        assert rec1.req_id_short == "-"

        # With contextvar on a fresh record
        rec2 = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="t.py",
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        token = current_request_id.set("abcdef12-3456-7890-abcd-ef1234567890")
        try:
            filter_obj.filter(rec2)
            assert rec2.request_id == "abcdef12-3456-7890-abcd-ef1234567890"
            assert rec2.req_id_short == "abcdef12"
        finally:
            current_request_id.reset(token)

    def test_pretty_dev_formatter_standard(self) -> None:
        """Formatter outputs short timestamp, truncated request_id, and extra attributes."""
        filter_obj = RequestContextFilter()
        formatter = PrettyDevFormatter()
        token = current_request_id.set("12345678-aaaa-bbbb-cccc-dddddddddddd")

        try:
            record = logging.LogRecord(
                name="test_logger",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg="Test message",
                args=(),
                exc_info=None,
            )
            record.payment_id = "pay_001"
            record.amount_cents = 5000
            filter_obj.filter(record)

            output = formatter.format(record)
            assert "INFO" in output
            assert "[12345678]" in output
            assert "test_logger: Test message" in output
            assert "payment_id=pay_001" in output
            assert "amount_cents=5000" in output
        finally:
            current_request_id.reset(token)

    def test_pretty_dev_formatter_with_exception_unformatted(self) -> None:
        """Formatter formats exc_info when exc_text is not yet populated."""
        formatter = PrettyDevFormatter()
        try:
            raise ValueError("Test formatting error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=20,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )
        assert record.exc_text is None
        output = formatter.format(record)
        assert "Error occurred" in output
        assert "ValueError: Test formatting error" in output

    def test_pretty_dev_formatter_with_existing_exc_text(self) -> None:
        """Formatter preserves and appends existing exc_text without re-formatting."""
        formatter = PrettyDevFormatter()
        try:
            raise RuntimeError("Underlying issue")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=30,
            msg="Pre-formatted error",
            args=(),
            exc_info=exc_info,
        )
        record.exc_text = "Custom pre-formatted stack trace text"
        output = formatter.format(record)
        assert "Pre-formatted error" in output
        assert "Custom pre-formatted stack trace text" in output

    def test_configure_logging(self) -> None:
        """configure_logging sets up stdout stream handler and sets log level."""
        configure_logging("DEBUG")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG
        assert any(isinstance(h.formatter, PrettyDevFormatter) for h in root_logger.handlers)

        # Reset to INFO
        configure_logging("INFO")
        assert root_logger.level == logging.INFO
