"""Integration test for Prometheus telemetry scrape endpoint (TC-16)."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_metrics_scrape_endpoint(client: httpx.AsyncClient) -> None:
    """TC-16: Scrape /metrics endpoint and verify Prometheus exposition format."""
    # 1. Issue an API request to generate HTTP request metrics
    await client.get("/health/live")

    # 2. Scrape Prometheus endpoint
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["Content-Type"]

    # 3. Assert core Prometheus metric symbols are present in exposition output
    metrics_text = response.text
    assert "http_requests_total" in metrics_text
    assert "http_request_duration_seconds" in metrics_text
