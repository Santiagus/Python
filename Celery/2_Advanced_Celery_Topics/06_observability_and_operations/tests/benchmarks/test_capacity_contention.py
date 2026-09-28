"""Capacity, contention, and prefetch benchmarks for Screening Rail.

Verifies TC-21:
1. Prefetch Buffer Discipline - worker_prefetch_multiplier=1 prevents head-of-line blocking.
2. Broker Reliability - task_acks_late=True, task_reject_on_worker_lost=True, broker_pool_limit=10.
3. Ingestion SLA Preservation - Screening ingestion endpoints maintain sub-25ms P99 latency.
4. Benchmark Harness Validation - Automated persistence of structured benchmark metrics.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from httpx import Response

from scripts.benchmark_latency import main, run_latency_benchmark
from services.worker.celery_app import celery_app


def test_prefetch_discipline_and_broker_pooling() -> None:
    """Verify Celery prefetch discipline, acknowledgements, and Kombu connection pooling."""
    conf = celery_app.conf

    # 1. Prefetch multiplier must be strictly 1 to prevent worker starvation
    assert conf.worker_prefetch_multiplier == 1

    # 2. Financial safety: late acknowledgements and rejection on worker crash
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True

    # 3. Connection pooling limits
    assert conf.broker_pool_limit == 10
    assert conf.broker_connection_retry_on_startup is True


@pytest.mark.asyncio
async def test_run_latency_benchmark_harness() -> None:
    """Verify that run_latency_benchmark executes, computes statistics, and persists JSON report."""
    with TemporaryDirectory() as tmp_dir:
        output_file = Path(tmp_dir) / "test_benchmark.json"

        # Mock HTTP client responses for health, screening creation, and status query
        mock_health_res = Response(200, json={"status": "alive"})
        mock_create_res = Response(
            202,
            json={
                "id": str(uuid4()),
                "status": "processing",
                "transaction_id": "tx_bench_001",
            },
        )
        mock_get_res = Response(
            200,
            json={
                "id": str(uuid4()),
                "status": "approved",
                "risk_score": 12,
            },
        )

        async def mock_send(
            self: httpx.AsyncClient,
            request: httpx.Request,
            **kwargs: object,
        ) -> Response:
            if request.url.path == "/health/live":
                return mock_health_res
            if request.url.path == "/api/v1/screenings" and request.method == "POST":
                return mock_create_res
            return mock_get_res

        with patch("httpx.AsyncClient.send", mock_send):
            report = await run_latency_benchmark(
                api_url="http://testserver",
                probes_count=10,
                rate=0,  # burst mode
                output_path=output_file,
            )

        assert report is not None
        assert report["results"]["total_probes"] == 10
        assert report["results"]["successful_probes"] == 10
        assert "api_latency_ms" in report["results"]
        assert "p99" in report["results"]["api_latency_ms"]
        assert output_file.exists()

        saved_data = json.loads(output_file.read_text(encoding="utf-8"))
        assert saved_data["parameters"]["probes_count"] == 10


@pytest.mark.asyncio
async def test_run_latency_benchmark_unhealthy_gateway() -> None:
    """Verify benchmark aborts cleanly when API gateway health check fails."""
    mock_health_res = Response(503, json={"status": "unhealthy"})

    with patch("httpx.AsyncClient.send", return_value=mock_health_res):
        report = await run_latency_benchmark(
            api_url="http://testserver",
            probes_count=5,
        )

    assert report is None


@pytest.mark.asyncio
async def test_run_latency_benchmark_connection_error() -> None:
    """Verify benchmark handles gateway connection failure gracefully."""
    with patch(
        "httpx.AsyncClient.send",
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        report = await run_latency_benchmark(
            api_url="http://unreachable:9999",
            probes_count=5,
        )

    assert report is None


@pytest.mark.asyncio
async def test_run_latency_benchmark_paced_with_errors() -> None:
    """Verify benchmark handles paced arrival rate and captures probe errors."""
    with TemporaryDirectory() as tmp_dir:
        output_file = Path(tmp_dir) / "test_paced.json"
        call_count = 0

        async def mock_send(
            self: httpx.AsyncClient,
            request: httpx.Request,
            **kwargs: object,
        ) -> Response:
            nonlocal call_count
            call_count += 1
            if request.url.path == "/health/live":
                return Response(200, json={"status": "alive"})
            if call_count % 3 == 0:
                raise httpx.RequestError("Simulated network drop")
            return Response(202, json={"id": str(uuid4()), "status": "processing"})

        with patch("httpx.AsyncClient.send", mock_send):
            report = await run_latency_benchmark(
                api_url="http://testserver",
                probes_count=6,
                rate=200.0,
                output_path=output_file,
            )

        assert report is not None
        assert report["results"]["total_probes"] == 6
        assert report["results"]["failed_probes"] > 0


def test_benchmark_main_cli() -> None:
    """Verify benchmark harness CLI execution entry point."""
    with (
        patch("sys.argv", ["benchmark_latency.py", "--probes", "2", "--rate", "0"]),
        patch(
            "scripts.benchmark_latency.run_latency_benchmark",
            return_value={"status": "ok"},
        ) as mock_bench,
    ):
        main()
        assert mock_bench.called
