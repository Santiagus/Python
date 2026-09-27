"""Unit tests for FastAPI modular middleware pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.logging_config import current_request_id
from app.middlewares import (
    CorrelationMiddleware,
    ErrorHandlingMiddleware,
    ProfilingMiddleware,
    register_middlewares,
)


@pytest.mark.asyncio
async def test_correlation_middleware_generates_id() -> None:
    """Verify CorrelationMiddleware generates a new UUID if header is missing."""
    middleware = CorrelationMiddleware(app=MagicMock())

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [],
    }
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        assert getattr(req.state, "request_id", None) is not None
        assert current_request_id.get() == req.state.request_id
        return Response("ok", status_code=200)

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert current_request_id.get() is None  # Reset token in finally


@pytest.mark.asyncio
async def test_correlation_middleware_preserves_incoming_id() -> None:
    """Verify CorrelationMiddleware propagates existing X-Request-ID."""
    middleware = CorrelationMiddleware(app=MagicMock())
    custom_id = str(uuid4())

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [(b"x-request-id", custom_id.encode())],
    }
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        assert req.state.request_id == custom_id
        return Response("ok", status_code=200)

    response = await middleware.dispatch(request, call_next)
    assert response.headers["X-Request-ID"] == custom_id


@pytest.mark.asyncio
async def test_error_handling_middleware_pass_through() -> None:
    """Verify ErrorHandlingMiddleware passes successful responses transparently."""
    middleware = ErrorHandlingMiddleware(app=MagicMock())
    scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        return Response("success", status_code=200)

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_error_handling_middleware_catches_unhandled_exception() -> None:
    """Verify ErrorHandlingMiddleware intercepts uncaught exceptions and returns 500 JSON."""
    middleware = ErrorHandlingMiddleware(app=MagicMock())
    scope = {"type": "http", "method": "POST", "path": "/crash", "headers": []}
    request = Request(scope)
    request.state.request_id = "test-error-req-id"

    async def call_next(req: Request) -> Response:
        raise RuntimeError("unhandled internal boom")

    response = await middleware.dispatch(request, call_next)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "test-error-req-id"


@pytest.mark.asyncio
async def test_profiling_middleware() -> None:
    """Verify ProfilingMiddleware records duration and attaches X-Process-Time-Ms."""
    middleware = ProfilingMiddleware(app=MagicMock())
    scope = {"type": "http", "method": "GET", "path": "/metrics", "headers": []}
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        return Response("ok", status_code=200)

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    assert "X-Process-Time-Ms" in response.headers


def test_register_middlewares() -> None:
    """Verify register_middlewares adds all middleware classes to FastAPI app."""
    mock_app = MagicMock()
    register_middlewares(mock_app)
    assert mock_app.add_middleware.call_count == 3
