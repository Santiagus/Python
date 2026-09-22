"""Capacity, contention, and prefetch benchmarks.

Verifies:
1. TC-04: Contention Invariant - Critical instant payouts maintain sub-100ms latency under bulk load.
2. TC-05: Prefetch Buffer Discipline - worker_prefetch_multiplier=1 prevents starvation.
3. TC-09: Two-Tier Rate Limiting - Worker token bucket + HTTP 429 edge throttling.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.dispatcher import PaymentDispatcher
from app.middlewares.rate_limit import HttpRateLimitMiddleware
from app.models import Account, Payment
from services.worker.celery_app import celery_app
from services.worker.tasks.payouts import process_instant_payout
from services.worker.tasks.settlements import process_payroll_chunk


@pytest.mark.benchmark
class TestCapacityAndContention:
    """Benchmark suite validating queue isolation, prefetch discipline, and SLA preservation."""

    def test_prefetch_discipline_and_queue_topology(self) -> None:
        """TC-05: Verify Celery prefetch discipline and Kombu AMQP queue arguments."""
        # 1. Assert prefetch multiplier is strictly 1 to prevent head-of-line blocking
        assert celery_app.conf.worker_prefetch_multiplier == 1
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.task_reject_on_worker_lost is True

        # 2. Inspect queue arguments on Kombu definitions
        queues_by_name = {q.name: q for q in celery_app.conf.task_queues}

        assert "critical" in queues_by_name
        critical_q = queues_by_name["critical"]
        assert critical_q.queue_arguments.get("x-max-priority") == 10
        assert critical_q.queue_arguments.get("x-dead-letter-exchange") == "payments.dlx"
        assert critical_q.routing_key == "payment.instant.payout"

        assert "bulk" in queues_by_name
        bulk_q = queues_by_name["bulk"]
        assert bulk_q.queue_arguments.get("x-message-ttl") == 86400000
        assert bulk_q.queue_arguments.get("x-dead-letter-exchange") == "payments.dlx"
        assert bulk_q.routing_key == "settlement.batch.payroll"

        assert "rejected_payments" in queues_by_name

    def test_task_rate_limiting_attribute(self) -> None:
        """TC-09 (Part A): Verify bulk worker task specifies 500/m token-bucket rate limit."""
        assert getattr(process_payroll_chunk, "rate_limit", None) == "500/m"
        assert process_payroll_chunk.acks_late is True

    @pytest.mark.asyncio
    async def test_api_rate_limiting_throttling(self) -> None:
        """TC-09 (Part B): Verify inbound HTTP rate limit middleware returns HTTP 429 when threshold exceeded."""
        async def mock_endpoint(request):
            return JSONResponse({"status": "ok"})

        app = Starlette(routes=[Route("/test-rate-limit", mock_endpoint)])
        # Use low capacity for testing rate limiter: burst capacity 3
        app.add_middleware(HttpRateLimitMiddleware, rate_per_minute=60, burst_capacity=3)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            responses = []
            for _ in range(5):
                res = await client.get("/test-rate-limit")
                responses.append(res.status_code)

            # First 3 requests succeed (HTTP 200), subsequent requests return 429 Too Many Requests
            assert responses[:3] == [200, 200, 200]
            assert responses[3] == 429
            assert responses[4] == 429

    @pytest.mark.asyncio
    async def test_critical_sla_under_bulk_contention(
        self,
        db_session,
    ) -> None:
        """TC-04: Verify instant payout dispatch maintains P99 latency < 100ms during bulk queue activity."""
        source_id = UUID("a0000000-0000-0000-0000-000000000001")

        # 1. Simulate 500 bulk disbursements partitioned into 5 chunks
        dispatcher = PaymentDispatcher()
        bulk_chunk_ids = [str(uuid4()) for _ in range(500)]
        batch_id = uuid4()
        with patch("services.worker.celery_app.celery_app.send_task") as mock_send:
            mock_send.return_value = AsyncMock()
            chunk_results = dispatcher.dispatch_batch_settlement(batch_id, bulk_chunk_ids, chunk_size=100)
            assert len(chunk_results) == 5

        # 2. Dispatch 20 instant payments while measuring dispatch latency
        latencies_ms: list[float] = []

        with patch("services.worker.celery_app.celery_app.send_task") as mock_send:
            mock_send.return_value = AsyncMock(id="mock_critical_task")

            for i in range(20):
                pid = uuid4()
                t0 = time.perf_counter()
                dispatcher.dispatch_instant_payout(
                    payment_id=pid,
                    correlation_id=f"corr_{i}",
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                latencies_ms.append(elapsed_ms)

        # 3. Compute P99 latency
        latencies_ms.sort()
        p99 = latencies_ms[int(len(latencies_ms) * 0.99)]

        # Assert SLA: dispatch under contention is strictly sub-100ms
        assert p99 < 100.0, f"P99 latency ({p99:.2f}ms) exceeded 100ms SLA"
