"""Integration tests for FastAPI middlewares and logging configuration (TC-09, TC-10, TC-11)."""

import logging
import uuid

import httpx
import pytest
from app.logging_config import DevelopmentLogFormatter, current_request_id, setup_logging
from app.middlewares import register_middlewares
from fastapi import FastAPI


@pytest.fixture
def middleware_app() -> FastAPI:
    """Create dedicated test FastAPI app configured with application middlewares."""
    test_app = FastAPI()
    register_middlewares(test_app)

    @test_app.get("/test/ok")
    async def ok_route() -> dict[str, str]:
        return {"status": "ok", "context_id": str(current_request_id.get())}

    @test_app.get("/test/boom")
    async def boom_route() -> None:
        raise RuntimeError("Simulated unhandled pipeline crash")

    return test_app


@pytest.mark.asyncio
async def test_correlation_id_middleware_with_custom_header(
    middleware_app: FastAPI,
) -> None:
    """TC-09: Incoming X-Request-ID is bound to ContextVar and echoed in response headers."""
    custom_id = f"custom-trace-{uuid.uuid4().hex[:6]}"
    transport = httpx.ASGITransport(app=middleware_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/test/ok", headers={"X-Request-ID": custom_id})
        assert res.status_code == 200
        assert res.headers["X-Request-ID"] == custom_id
        assert res.json()["context_id"] == custom_id
        assert "X-Process-Time-Ms" in res.headers


@pytest.mark.asyncio
async def test_correlation_id_middleware_auto_generation(
    middleware_app: FastAPI,
) -> None:
    """TC-10: Missing X-Request-ID triggers automatic UUIDv4 generation."""
    transport = httpx.ASGITransport(app=middleware_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/test/ok")
        assert res.status_code == 200
        auto_id = res.headers.get("X-Request-ID")
        assert auto_id is not None
        # Verify valid UUID format
        parsed_uuid = uuid.UUID(auto_id)
        assert str(parsed_uuid) == auto_id


@pytest.mark.asyncio
async def test_error_handling_middleware_catches_unhandled_exception(
    middleware_app: FastAPI,
) -> None:
    """TC-11: Unhandled exception is intercepted, returning normalized JSON 500."""
    custom_id = "error-audit-1234"
    transport = httpx.ASGITransport(app=middleware_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/test/boom", headers={"X-Request-ID": custom_id})
        assert res.status_code == 500
        data = res.json()
        assert data["detail"] == "Internal server error occurred"
        assert data["request_id"] == custom_id
        assert res.headers["X-Request-ID"] == custom_id


def test_development_log_formatter() -> None:
    """Verify pretty log formatter formats records with timestamps and context."""
    formatter = DevelopmentLogFormatter()
    token = current_request_id.set("abcdef12-3456-7890-abcd-ef1234567890")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="User %s logged in",
            args=("admin",),
            exc_info=None,
        )
        record.__dict__["extra_key"] = "extra_val"
        formatted = formatter.format(record)
        assert "[abcdef12]" in formatted
        assert "User admin logged in" in formatted
        assert "extra_key=extra_val" in formatted
    finally:
        current_request_id.reset(token)

    # Test setup_logging function
    setup_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.asyncio
async def test_profiling_middleware_unhandled_exception() -> None:
    """Verify profiling middleware observes 500 status when unhandled exception occurs."""
    from app.middlewares.profiling import ProfilingMiddleware

    raw_app = FastAPI()
    raw_app.add_middleware(ProfilingMiddleware)

    @raw_app.get("/crash")
    async def crash_endpoint() -> None:
        raise ValueError("Fatal crash")

    transport = httpx.ASGITransport(app=raw_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/crash")
        assert res.status_code == 500
