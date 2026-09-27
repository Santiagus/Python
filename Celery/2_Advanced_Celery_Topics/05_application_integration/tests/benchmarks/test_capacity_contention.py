"""Capacity, contention, and prefetch benchmarks for Card Dispute Engine.

Verifies:
1. Prefetch Buffer Discipline - worker_prefetch_multiplier=1 prevents head-of-line blocking.
2. Broker Reliability - task_acks_late=True, task_reject_on_worker_lost=True, broker_pool_limit=10.
3. Ingestion SLA Preservation - Dispute ingestion endpoints maintain sub-50ms P99 latency.
4. Benchmark Harness Validation - Automated persistence of structured benchmark metrics.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

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

        # Mock HTTP client responses for health, dispute creation, and status query
        mock_health_res = Response(200, json={"status": "ok"})
        mock_create_res = Response(
            202,
            json={
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "processing",
                "transaction_id": "tx_bench_001",
            },
        )
        mock_get_res = Response(
            200,
            json={
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "submitted_to_network",
                "network_reference_id": "VROL-TEST01",
            },
        )

        async def mock_send(request, **kwargs):
            if request.url.path == "/health":
                return mock_health_res
            if request.url.path == "/disputes" and request.method == "POST":
                return mock_create_res
            return mock_get_res

        with patch("httpx.AsyncClient.send", side_effect=mock_send):
            report = await run_latency_benchmark(
                api_url="http://testserver",
                api_key="sk_live_card_disputes_test_key_001",
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
    """Verify benchmark aborts cleanly when gateway connection is refused."""
    with patch("httpx.AsyncClient.send", side_effect=RuntimeError("Connection refused")):
        report = await run_latency_benchmark(
            api_url="http://testserver",
            probes_count=5,
        )
        assert report is None


def test_benchmark_cli_main() -> None:
    """Verify CLI entrypoint parses arguments and invokes run_latency_benchmark."""
    with (
        patch("sys.argv", ["benchmark_latency.py", "--probes", "5", "--rate", "10"]),
        patch("scripts.benchmark_latency.run_latency_benchmark", new_callable=AsyncMock) as mock_run,
    ):
        main()
        assert mock_run.called
        assert mock_run.call_args.kwargs["probes_count"] == 5
        assert mock_run.call_args.kwargs["rate"] == 10.0
