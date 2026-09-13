"""Unit tests for logging configuration and centralized ErrorHandlingMiddleware."""

import logging
from unittest.mock import patch
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.logging_config import configure_logging
from app.main import ErrorHandlingMiddleware


def test_configure_logging_pretty() -> None:
    """Verify configure_logging configures human-readable pretty formatting."""
    configure_logging(level="DEBUG", log_format="pretty")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, logging.Formatter)


def test_configure_logging_json() -> None:
    """Verify configure_logging configures structured JSON formatting."""
    configure_logging(level="INFO", log_format="json")
    root = logging.getLogger()
    assert root.level == logging.INFO
    assert len(root.handlers) == 1


def test_effective_log_format_defaults() -> None:
    """Settings should default to pretty in development and json in production."""
    dev_settings = Settings(environment="development", log_format=None)
    assert dev_settings.effective_log_format == "pretty"

    prod_settings = Settings(environment="production", log_format=None)
    assert prod_settings.effective_log_format == "json"

    override_settings = Settings(environment="production", log_format="pretty")
    assert override_settings.effective_log_format == "pretty"


@pytest.mark.asyncio
async def test_error_handling_middleware_catches_unhandled_exception() -> None:
    """Middleware must catch unexpected exceptions, log, and return 500 without crashing."""
    test_app = FastAPI()
    test_app.add_middleware(ErrorHandlingMiddleware)

    @test_app.get("/crash")
    async def crash_endpoint():
        raise RuntimeError("Unexpected boom!")

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/crash", headers={"X-Request-ID": "test-req-123"})
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "internal server error"
        assert data["request_id"] == "test-req-123"
        assert response.headers["X-Request-ID"] == "test-req-123"


@pytest.mark.asyncio
async def test_error_handling_middleware_generates_request_id() -> None:
    """Middleware must generate an X-Request-ID header if not supplied by client."""
    test_app = FastAPI()
    test_app.add_middleware(ErrorHandlingMiddleware)

    @test_app.get("/ok")
    async def ok_endpoint():
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/ok")
        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0


def test_pretty_formatter_defaults_are_empty_not_dash() -> None:
    """Missing fields must default to empty and never print '-' or dummy dashes."""
    from app.logging_config import PrettyFormatter

    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="app.routes",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="create_application_requested",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)
    assert output.endswith("INFO app.routes create_application_requested")
    assert "- - - - -ms" not in output
    assert " - " not in output
    assert "ms" not in output


def test_pretty_formatter_no_ms_when_duration_missing() -> None:
    """Do not print time units 'ms' if duration_ms value is missing, None, or empty."""
    from app.logging_config import PrettyFormatter

    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="app.main",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="request_complete",
        args=(),
        exc_info=None,
    )
    record.request_id = "test-uui"
    record.method = "GET"
    record.path = "/api/v1/applications"
    record.status_code = 200
    # duration_ms intentionally omitted

    output = formatter.format(record)
    assert output.endswith("test-uui GET /api/v1/applications 200")
    assert "ms" not in output
    assert "- - - - -ms" not in output
    assert " - " not in output


def test_pretty_formatter_trims_timestamp_to_time_only() -> None:
    """Timestamp in pretty mode should be time-only (%H:%M:%S) without date or milliseconds."""
    import re
    from app.logging_config import PrettyFormatter

    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="app.routes",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="service_ping",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    timestamp = output.split(" ", 1)[0]
    # Verify format is strictly HH:MM:SS (e.g. 11:28:45)
    assert re.match(r"^\d{2}:\d{2}:\d{2}$", timestamp)


def test_pretty_formatter_shortens_uuid_request_id() -> None:
    """Long UUID request IDs should be truncated to the first 8 characters in pretty mode."""
    from app.logging_config import PrettyFormatter

    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="app.main",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="request_complete",
        args=(),
        exc_info=None,
    )
    record.request_id = "c1655027-2c97-40d2-9ae4-0d3227a9ffec"
    record.method = "POST"
    record.path = "/api/v1/applications"
    record.status_code = 201
    record.duration_ms = 42.1

    output = formatter.format(record)
    assert "c1655027 POST /api/v1/applications 201 42.1ms" in output
    assert "c1655027-2c97-40d2-9ae4-0d3227a9ffec" not in output


def test_pretty_formatter_extra_dictionary_items_printed() -> None:
    """All extra dictionary items passed in the log call must be printed in the log output."""
    from app.logging_config import PrettyFormatter

    formatter = PrettyFormatter()
    record = logging.LogRecord(
        name="app.routes",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="create_application_requested",
        args=(),
        exc_info=None,
    )
    record.company_name = "Acme Industrial Logistics Ltd"
    record.applicant_name = "Eleanor Vance"
    record.requested_facility = 1500000.0

    output = formatter.format(record)
    assert "create_application_requested" in output
    assert "company_name='Acme Industrial Logistics Ltd'" in output
    assert "applicant_name='Eleanor Vance'" in output
    assert "requested_facility=1500000.0" in output
    assert "- - - - -ms" not in output
    assert " - " not in output
    assert "ms " not in output and not output.endswith("ms")


def test_request_context_filter_injects_request_id() -> None:
    """RequestContextFilter should inject current_request_id into log records."""
    from app.logging_config import RequestContextFilter, current_request_id

    filter_ = RequestContextFilter()
    record = logging.LogRecord(
        name="app.routes",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="create_application_requested",
        args=(),
        exc_info=None,
    )

    token = current_request_id.set("ctx-req-999")
    try:
        filter_.filter(record)
        assert getattr(record, "request_id", None) == "ctx-req-999"
    finally:
        current_request_id.reset(token)

