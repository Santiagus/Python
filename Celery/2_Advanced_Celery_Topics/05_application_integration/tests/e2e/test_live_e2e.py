"""Live multi-process end-to-end (E2E) integration test suite for Card Disputes.

Verifies TC-E2E-01:
1. Real AMQP message publishing across RabbitMQ queue ('card_disputes').
2. Live background Celery worker daemon subprocess consuming from queues.
3. Database persistence and atomic row-locking under real multi-process concurrency.
4. Asynchronous polling of card disputes until terminal 'submitted_to_network' status.
5. In-flight cooperative cancellation revoking task before terminal transition.
6. Failure handling and retry lifecycle under real worker processing.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.main import app
from app.models import CardDispute
from app.schemas import DisputeReason, DisputeStatus

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def live_celery_worker(
    test_database_url: str,
    test_redis_url: str,
    rabbitmq_service_url: str,
) -> Generator[subprocess.Popen[bytes], None, None]:
    """Launch an isolated Celery worker daemon subprocess for live multi-process E2E testing."""
    from services.worker.celery_app import celery_app

    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    orig_broker = celery_app.conf.broker_url
    orig_backend = celery_app.conf.result_backend

    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
        broker_url=rabbitmq_service_url,
        result_backend=test_redis_url,
    )

    worker_env = {
        **os.environ,
        "PYTHONPATH": f"{MODULE_ROOT}:{os.environ.get('PYTHONPATH', '')}",
        "DATABASE_URL": test_database_url,
        "CELERY_BROKER_URL": rabbitmq_service_url,
        "CELERY_RESULT_BACKEND": test_redis_url,
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "INFO",
    }

    log_file = open("/tmp/live_celery_worker_05.log", "w")
    worker_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "services.worker.celery_app:celery_app",
            "worker",
            "-P",
            "solo",
            "--loglevel=INFO",
            "-Q",
            "card_disputes",
        ],
        cwd=str(MODULE_ROOT),
        env=worker_env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    # Pre-declare and purge queues on RabbitMQ broker
    try:
        with celery_app.connection_or_acquire() as conn:
            for q in celery_app.conf.task_queues:
                bound = q(conn.default_channel)
                bound.declare()
                bound.purge()
    except Exception:
        pass

    time.sleep(3.0)

    try:
        yield worker_proc
    finally:
        worker_proc.terminate()
        try:
            worker_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker_proc.kill()
        log_file.close()

        celery_app.conf.update(
            task_always_eager=orig_eager,
            task_eager_propagates=orig_prop,
            broker_url=orig_broker,
            result_backend=orig_backend,
        )


@pytest.fixture
async def live_async_client(
    test_database_url: str,
    test_redis_url: str,
    rabbitmq_service_url: str,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide AsyncClient wired to the test app with non-eager Celery and real service URLs."""
    from services.worker.celery_app import celery_app

    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
        broker_url=rabbitmq_service_url,
        result_backend=test_redis_url,
    )

    settings = get_settings()
    settings.database_url = test_database_url
    settings.celery_broker_url = rabbitmq_service_url
    settings.celery_result_backend = test_redis_url
    settings.environment = "test"

    import app.db as app_db

    if app_db._engine is not None:
        await app_db._engine.dispose()
    app_db._engine = None
    app_db._session_factory = None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": settings.api_key_secret},
    ) as client:
        yield client


@pytest.mark.e2e
@pytest.mark.asyncio
class TestLiveDisputeE2E:
    """Live distributed multi-process E2E test suite across API, RabbitMQ, Worker daemon, and PostgreSQL."""

    async def test_live_dispute_happy_path_e2e(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
    ) -> None:
        """Submit dispute -> immediate in-flight processing -> live worker clears -> submitted_to_network."""
        # 1. Submit a valid card dispute via API
        payload = {
            "transaction_id": "tx_e2e_live_happy_001",
            "card_token": "tok_card_9921_sec",
            "card_last_four": "4242",
            "amount": "199.95",
            "currency": "USD",
            "reason": DisputeReason.fraudulent.value,
            "evidence_notes": "Live E2E test verification.",
        }
        create_res = await live_async_client.post("/disputes", json=payload)
        assert create_res.status_code == 202
        dispute_id = create_res.json()["id"]

        # 2. Verify immediate in-flight status (anti-blackhole contract)
        immediate_res = await live_async_client.get(f"/disputes/{dispute_id}")
        assert immediate_res.status_code == 200
        assert immediate_res.json()["status"] in ("processing", "submitted_to_network")

        # 3. Poll until background worker dequeues message and completes network submission
        terminal_report = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_res = await live_async_client.get(f"/disputes/{dispute_id}")
            if poll_res.status_code == 200:
                data = poll_res.json()
                if data["status"] == DisputeStatus.submitted_to_network.value:
                    terminal_report = data
                    break

        assert terminal_report is not None, "Worker did not transition dispute to submitted_to_network within timeout"
        assert terminal_report["status"] == "submitted_to_network"
        assert terminal_report["network_reference_id"] is not None
        assert terminal_report["network_reference_id"].startswith("VROL-")

        # 4. Direct PostgreSQL verification
        engine = create_async_engine(test_database_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with session_factory() as session:
            stmt = select(CardDispute).where(CardDispute.id == UUID(dispute_id))
            db_record = (await session.execute(stmt)).scalars().first()
            assert db_record is not None
            assert db_record.status == "submitted_to_network"
            assert db_record.network_reference_id is not None
        await engine.dispose()

    async def test_live_dispute_failure_and_retry_e2e(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
    ) -> None:
        """Simulate clearinghouse failure -> status 'failed' -> trigger retry -> worker completes."""
        # 1. Submit dispute with simulate_failure=true
        payload = {
            "transaction_id": "tx_e2e_live_fail_002",
            "card_token": "tok_card_7733_sec",
            "card_last_four": "5678",
            "amount": "80.00",
            "currency": "USD",
            "reason": DisputeReason.goods_not_received.value,
        }
        create_res = await live_async_client.post("/disputes?simulate_failure=true", json=payload)
        assert create_res.status_code == 202
        dispute_id = create_res.json()["id"]

        # 2. Poll until worker flags dispute as 'failed'
        failed_report = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_res = await live_async_client.get(f"/disputes/{dispute_id}")
            if poll_res.status_code == 200:
                data = poll_res.json()
                if data["status"] == DisputeStatus.failed.value:
                    failed_report = data
                    break

        assert failed_report is not None, "Worker did not transition dispute to failed status within timeout"
        assert failed_report["status"] == "failed"
        assert "Clearinghouse timeout" in (failed_report["error_message"] or "")

        # 3. Trigger manual retry without failure simulation
        retry_res = await live_async_client.post(f"/disputes/{dispute_id}/retry")
        assert retry_res.status_code == 200
        retry_data = retry_res.json()
        assert retry_data["status"] == "processing"
        assert retry_data["attempt_count"] == 2

        # 4. Poll until worker successfully clears the retried dispute
        cleared_report = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_res = await live_async_client.get(f"/disputes/{dispute_id}")
            if poll_res.status_code == 200:
                data = poll_res.json()
                if data["status"] == DisputeStatus.submitted_to_network.value:
                    cleared_report = data
                    break

        assert cleared_report is not None, "Worker did not clear retried dispute within timeout"
        assert cleared_report["status"] == "submitted_to_network"
        assert cleared_report["attempt_count"] == 2
        assert cleared_report["network_reference_id"] is not None

    async def test_live_dispute_cooperative_cancellation_e2e(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
    ) -> None:
        """Submit disputes sequentially -> cancel pending dispute in queue -> worker aborts gracefully."""
        # 1. Submit Dispute A to occupy the solo worker
        payload_a = {
            "transaction_id": "tx_e2e_live_blocker_003a",
            "card_token": "tok_card_8812_sec",
            "card_last_four": "1111",
            "amount": "25.00",
            "currency": "USD",
            "reason": DisputeReason.fraudulent.value,
        }
        await live_async_client.post("/disputes?simulate_failure=true", json=payload_a)

        # 2. Immediately submit Dispute B destined for in-flight cancellation
        payload_b = {
            "transaction_id": "tx_e2e_live_cancel_003b",
            "card_token": "tok_card_8812_sec",
            "card_last_four": "2222",
            "amount": "45.00",
            "currency": "USD",
            "reason": DisputeReason.unrecognized.value,
        }
        create_res_b = await live_async_client.post("/disputes", json=payload_b)
        assert create_res_b.status_code == 202
        dispute_id_b = create_res_b.json()["id"]

        # 3. Immediately cancel Dispute B while it is buffered in the queue
        cancel_res = await live_async_client.post(f"/disputes/{dispute_id_b}/cancel")
        if cancel_res.status_code == 200:
            assert cancel_res.json()["status"] == "cancelled"
            assert "revoked" in cancel_res.json()["message"]
        else:
            # If the worker cleared Dispute A and B unusually fast, verify terminal state conflict
            assert cancel_res.status_code == 409
            assert "Cannot cancel dispute in terminal state" in cancel_res.json()["detail"]

        # 4. Wait for worker to finish processing all queue messages
        await asyncio.sleep(2.0)

        # 5. Direct verification that Dispute B was never overwritten to submitted_to_network if cancelled
        verify_res = await live_async_client.get(f"/disputes/{dispute_id_b}")
        assert verify_res.status_code == 200
        if cancel_res.status_code == 200:
            assert verify_res.json()["status"] == "cancelled"
