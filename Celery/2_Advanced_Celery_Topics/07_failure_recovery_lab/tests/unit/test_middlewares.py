"""Unit tests for FastAPI correlation and error handling middlewares."""

import pytest
from fastapi import FastAPI, HTTPException, Request, status
from httpx import ASGITransport, AsyncClient

from app.middlewares import (
    CorrelationMiddleware,
    ErrorHandlingMiddleware,
    get_current_request_id,
    register_middlewares,
)


@pytest.mark.asyncio
async def test_correlation_middleware_generates_id_when_absent() -> None:
    """Verify that an 8-character correlation ID is generated when X-Request-ID is absent."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    captured_ctx_id: str | None = None
    captured_state_id: str | None = None

    @app.get("/test")
    async def endpoint(request: Request) -> dict[str, str]:
        nonlocal captured_ctx_id, captured_state_id
        captured_ctx_id = get_current_request_id()
        captured_state_id = getattr(request.state, "request_id", None)
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test")

    assert response.status_code == 200
    res_header = response.headers.get("X-Request-ID")
    assert res_header is not None
    assert len(res_header) == 8
    assert captured_ctx_id == res_header
    assert captured_state_id == res_header
    assert get_current_request_id() is None


@pytest.mark.asyncio
async def test_correlation_middleware_preserves_custom_id() -> None:
    """Verify that an incoming X-Request-ID header is preserved and propagated."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    custom_id = "CORREL-WIRE-9921"

    @app.get("/test")
    async def endpoint(request: Request) -> dict[str, str]:
        assert get_current_request_id() == custom_id
        assert getattr(request.state, "request_id", None) == custom_id
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test", headers={"X-Request-ID": custom_id})

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id
    assert get_current_request_id() is None


@pytest.mark.asyncio
async def test_correlation_middleware_handles_empty_or_whitespace_header() -> None:
    """Verify that empty or whitespace-only X-Request-ID results in a generated 8-char ID."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/test")
    async def endpoint() -> dict[str, str]:
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test", headers={"X-Request-ID": "   "})

    assert response.status_code == 200
    res_header = response.headers.get("X-Request-ID")
    assert res_header is not None
    assert len(res_header) == 8


@pytest.mark.asyncio
async def test_correlation_middleware_resets_contextvar_on_endpoint_error() -> None:
    """Verify that ContextVar is cleanly reset even when the downstream handler raises."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/error")
    async def error_endpoint() -> None:
        assert get_current_request_id() is not None
        raise RuntimeError("Unexpected boom")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="Unexpected boom"):
            await client.get("/error")

    # Verify contextvar is reset
    assert get_current_request_id() is None


@pytest.mark.asyncio
async def test_error_handling_middleware_catches_unhandled_exception() -> None:
    """Verify that unhandled exceptions are caught and sanitized to 500 JSON responses."""
    app = FastAPI()
    app.add_middleware(ErrorHandlingMiddleware)

    @app.get("/crash")
    async def crash_endpoint() -> None:
        raise ValueError("Fatal internal crash")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/crash", headers={"X-Request-ID": "crash-123"})

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["request_id"] == "crash-123"
    assert response.headers.get("X-Request-ID") == "crash-123"


@pytest.mark.asyncio
async def test_error_handling_middleware_logs_warning_on_4xx() -> None:
    """Verify that 4xx client errors are logged as warnings and returned cleanly."""
    app = FastAPI()
    app.add_middleware(ErrorHandlingMiddleware)

    @app.get("/not-found")
    async def not_found_endpoint() -> None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/not-found")

    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}


@pytest.mark.asyncio
async def test_error_handling_middleware_handles_missing_request_id() -> None:
    """Verify fallback when request has neither state.request_id nor X-Request-ID header."""
    app = FastAPI()
    app.add_middleware(ErrorHandlingMiddleware)

    @app.get("/plain")
    async def plain_endpoint() -> dict[str, str]:
        return {"hello": "world"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/plain")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "unknown"


@pytest.mark.asyncio
async def test_register_middlewares_full_integration() -> None:
    """Verify end-to-end operation of registered correlation and error handling middlewares."""
    app = FastAPI()
    register_middlewares(app)

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        ctx_id = get_current_request_id()
        assert ctx_id is not None
        return {"pong": ctx_id}

    @app.get("/api/v1/fail")
    async def fail() -> None:
        raise KeyError("Missing required key")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Success case with automatic ID generation
        res_ok = await client.get("/api/v1/ping")
        assert res_ok.status_code == 200
        req_id = res_ok.headers.get("X-Request-ID")
        assert req_id is not None
        assert res_ok.json()["pong"] == req_id

        # 2. Crash case trapped by error handler with correlation ID preserved
        res_fail = await client.get("/api/v1/fail", headers={"X-Request-ID": "audit-track-99"})
        assert res_fail.status_code == 500
        assert res_fail.headers.get("X-Request-ID") == "audit-track-99"
        assert res_fail.json() == {
            "detail": "Internal server error",
            "request_id": "audit-track-99",
        }
