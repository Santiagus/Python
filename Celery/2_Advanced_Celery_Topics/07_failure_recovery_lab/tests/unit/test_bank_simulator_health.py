"""Unit tests for Bank Simulator API health endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from services.bank_simulator_api.main import app


@pytest.mark.asyncio
async def test_bank_simulator_health_check() -> None:
    """Verify that the Bank Simulator API health check returns HTTP 200 and status ok."""
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
