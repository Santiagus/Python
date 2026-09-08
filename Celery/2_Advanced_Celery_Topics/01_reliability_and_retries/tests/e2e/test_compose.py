import os

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("E2E_BASE_URL"),
    reason="set E2E_BASE_URL to run against Docker Compose",
)


@pytest.mark.asyncio
async def test_compose_health_endpoints():
    base_url = os.environ["E2E_BASE_URL"]
    async with httpx.AsyncClient(base_url=base_url, timeout=5) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
