"""Unit tests for FastAPI Ingestion Gateway health endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_app_health_check() -> None:
    """Verify that the FastAPI ingestion gateway health check returns HTTP 200 and status ok."""
    # 1. Create ASGI transport client
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        # 2. Invoke health endpoint
        response = await client.get("/health")

        # 3. Assert status and payload
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
