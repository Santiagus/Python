"""Integration tests for the modular 5-layer middleware pipeline."""

from __future__ import annotations

import logging
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest

from app.logging_config import current_request_id
from app.middlewares import register_middlewares
from app.middlewares.profiling import SLA_WARNING_THRESHOLD_MS


def create_test_app_with_middlewares() -> FastAPI:
    """Create a minimal FastAPI test app equipped with the 5-layer middleware stack."""
    test_app = FastAPI()
    register_middlewares(test_app)

    @test_app.get("/test/ok")
    async def ok_route():
        return {"message": "success", "current_context_id": current_request_id.get()}

    @test_app.get("/test/slow")
    async def slow_route():
        import asyncio
        await asyncio.sleep(0.12)  # > 100ms threshold
        return {"message": "slow"}

    @test_app.get("/test/crash")
    async def crash_route():
        raise RuntimeError("Intentional unhandled route crash for 500 shielding")

    @test_app.get("/test/http-error")
    async def http_error_route():
        raise HTTPException(status_code=400, detail="Client validation error")

    return test_app


@pytest.mark.integration
class TestMiddlewarePipeline:
    """Test correlation, defensive security headers, error shielding, and profiling."""

    @pytest.mark.asyncio
    async def test_correlation_id_generation_and_contextvar(self) -> None:
        """When no X-Request-ID is provided, a fresh UUID is generated and bound to ContextVar."""
        app = create_test_app_with_middlewares()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/test/ok")
            assert res.status_code == 200
            assert "X-Request-ID" in res.headers
            gen_id = res.headers["X-Request-ID"]
            assert len(gen_id) >= 32
            # Verify route handler received the same ID in ContextVar
            assert res.json()["current_context_id"] == gen_id

    @pytest.mark.asyncio
    async def test_correlation_id_preservation(self) -> None:
        """Inbound X-Request-ID header is preserved across the lifecycle and returned."""
        app = create_test_app_with_middlewares()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client_id = "req_custom_trace_999"
            res = await client.get("/test/ok", headers={"X-Request-ID": client_id})
            assert res.status_code == 200
            assert res.headers["X-Request-ID"] == client_id
            assert res.json()["current_context_id"] == client_id

    @pytest.mark.asyncio
    async def test_security_defensive_headers(self) -> None:
        """Outgoing responses must contain enterprise defensive security headers."""
        app = create_test_app_with_middlewares()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/test/ok")
            assert res.headers["X-Content-Type-Options"] == "nosniff"
            assert res.headers["X-Frame-Options"] == "DENY"
            assert "max-age=" in res.headers["Strict-Transport-Security"]
            assert "default-src 'self'" in res.headers["Content-Security-Policy"]
            assert res.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
            assert res.headers["X-XSS-Protection"] == "0"

    @pytest.mark.asyncio
    async def test_security_headers_preserve_existing(self) -> None:
        """If route handler explicitly sets a security header, middleware must not overwrite it."""
        app = create_test_app_with_middlewares()

        @app.get("/test/custom-header")
        async def custom_header_route():
            from starlette.responses import JSONResponse
            return JSONResponse({"custom": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/test/custom-header")
            assert res.headers["X-Frame-Options"] == "SAMEORIGIN"

    @pytest.mark.asyncio
    async def test_error_handling_500_shielding(self) -> None:
        """Unhandled exceptions must be caught and normalized to JSON 500 with request_id."""
        app = create_test_app_with_middlewares()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/test/crash", headers={"X-Request-ID": "req_crash_123"})
            assert res.status_code == 500
            body = res.json()
            assert body["detail"] == "internal server error"
            assert body["request_id"] == "req_crash_123"
            assert res.headers["X-Request-ID"] == "req_crash_123"

    @pytest.mark.asyncio
    async def test_profiling_headers_and_telemetry(self) -> None:
        """Profiling middleware must attach response latency and rate-limit headers."""
        app = create_test_app_with_middlewares()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/test/ok")
            assert "X-Response-Time-Ms" in res.headers
            assert float(res.headers["X-Response-Time-Ms"]) >= 0.0
            assert res.headers["X-RateLimit-Limit"] == "600"
            assert res.headers["X-RateLimit-Remaining"] == "599"

    @pytest.mark.asyncio
    async def test_profiling_sla_warning_threshold(self) -> None:
        """When route exceeds SLA threshold (100ms), a warning must be logged."""
        app = create_test_app_with_middlewares()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.middlewares.profiling.logger.warning") as mock_warn:
                res = await client.get("/test/slow")
                assert res.status_code == 200
                assert mock_warn.called
                assert mock_warn.call_args[0][0] == "sla_latency_warning"

    @pytest.mark.asyncio
    async def test_profiling_error_event_logging(self) -> None:
        """HTTP error responses emit 'request_error' log event."""
        app = create_test_app_with_middlewares()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.middlewares.profiling.logger.info") as mock_info:
                res = await client.get("/test/http-error")
                assert res.status_code == 400
                assert any(call[0][0] == "request_error" for call in mock_info.call_args_list)

    @pytest.mark.asyncio
    async def test_rate_limit_disabled_when_zero(self) -> None:
        """When requests_per_minute is 0 or negative, rate limiting is bypassed."""
        app = FastAPI()
        register_middlewares(app, requests_per_minute=0)

        @app.get("/test/unlimited")
        async def unlimited_route():
            return {"status": "unlimited"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/test/unlimited")
            assert res.status_code == 200
            assert res.headers["X-RateLimit-Limit"] == "unlimited"
            assert res.headers["X-RateLimit-Remaining"] == "unlimited"

