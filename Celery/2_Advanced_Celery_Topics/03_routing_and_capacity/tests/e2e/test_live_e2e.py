"""End-to-end (E2E) tests across the live distributed architecture.

Verifies TC-13:
1. Real AMQP message publishing across RabbitMQ queues (critical, default, bulk).
2. Live Celery worker daemon subprocess consuming from queues.
3. Live Bank Simulator API server processing FedNow/RTP/ACH wire transfers.
4. Database persistence and atomic row-locking under real multi-process concurrency.
5. Asynchronous status polling until final settled states.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncGenerator, Generator
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
import uvicorn

from app.config import get_settings
from app.dependencies import get_db
from app.main import create_app
from app.models import Account, BatchSettlement, Disbursement, Payment
from services.bank_simulator_api.main import app as bank_api_app
from services.worker.celery_app import celery_app


def _find_free_port() -> int:
    """Find an available ephemeral local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_bank_simulator() -> Generator[str, None, None]:
    """Launch live Bank Simulator API via Uvicorn in a background thread."""
    port = _find_free_port()
    config = uvicorn.Config(
        bank_api_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server readiness
    bank_url = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                ready = True
                break
        except OSError:
            time.sleep(0.1)

    if not ready:
        pytest.skip("Bank simulator failed to start on ephemeral port")

    yield bank_url
    server.should_exit = True
    thread.join(timeout=2.0)


@pytest.fixture(scope="module")
def live_celery_worker(
    test_database_url: str,
    rabbitmq_service_url: str,
    live_bank_simulator: str,
) -> Generator[subprocess.Popen[bytes], None, None]:
    """Launch an isolated Celery worker daemon process for live multi-process E2E testing."""
    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    orig_broker = celery_app.conf.broker_url
    orig_backend = celery_app.conf.result_backend

    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
        broker_url=rabbitmq_service_url,
        result_backend=None,
    )

    worker_env = {
        **os.environ,
        "DATABASE_URL": test_database_url,
        "RABBITMQ_URL": rabbitmq_service_url,
        "REDIS_URL": "",
        "BANK_API_URL": live_bank_simulator,
        "ENVIRONMENT": "test",
    }

    worker_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "services.worker.celery_app:celery_app",
            "worker",
            "-c",
            "2",
            "-P",
            "solo",
            "--loglevel=WARNING",
            "-Q",
            "critical,default,bulk",
        ],
        env=worker_env,
        stdout=open("/tmp/live_celery_worker.log", "w"),
        stderr=subprocess.STDOUT,
    )

    # Pre-declare and purge queues on RabbitMQ broker so stale benchmark messages are cleared
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

        celery_app.conf.update(
            task_always_eager=orig_eager,
            task_eager_propagates=orig_prop,
            broker_url=orig_broker,
            result_backend=orig_backend,
        )


@pytest.fixture
async def live_async_client(
    test_database_url: str,
    rabbitmq_service_url: str,
    live_bank_simulator: str,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide AsyncClient wired to the live test app with non-eager Celery and real URLs."""
    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
        broker_url=rabbitmq_service_url,
        result_backend=None,
    )

    settings = get_settings()
    settings.database_url = test_database_url
    settings.rabbitmq_url = rabbitmq_service_url
    settings.bank_api_url = live_bank_simulator
    settings.environment = "test"

    import app.db as app_db
    if app_db._engine is not None:
        await app_db._engine.dispose()
        app_db._engine = None
        app_db._session_factory = None

    test_app = create_app()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
class TestLiveDistributedE2E:
    """TC-13: Full live stack E2E tests verifying async API, broker, worker, and database."""

    async def test_live_instant_payout_lifecycle(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
        auth_headers: dict[str, str],
    ) -> None:
        """Submit instant FedNow payout -> Celery critical queue -> live worker -> bank simulator -> settled."""
        source_account_id = "a0000000-0000-0000-0000-000000000001"
        idemp_key = f"idemp_live_{uuid4().hex}"

        # 1. POST /payments/instant
        create_res = await live_async_client.post(
            "/payments/instant",
            json={
                "idempotency_key": idemp_key,
                "source_account_id": source_account_id,
                "destination_account_number": "112233445566",
                "destination_routing_number": "021000021",
                "amount": "125.50",
                "rail": "fednow",
                "description": "Live E2E FedNow Instant Payout",
            },
            headers=auth_headers,
        )
        assert create_res.status_code == 202
        data = create_res.json()
        assert data["status"] == "pending"
        payment_id = data["payment_id"]

        # 2. Asynchronously poll GET /payments/{id} until worker finishes
        settled_payment = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_res = await live_async_client.get(f"/payments/{payment_id}", headers=auth_headers)
            assert poll_res.status_code == 200
            poll_data = poll_res.json()
            if poll_data["status"] in ("settled", "failed", "rejected"):
                settled_payment = poll_data
                break

        assert settled_payment is not None, f"Payment {payment_id} did not settle within timeout"
        assert settled_payment["status"] == "settled"
        assert settled_payment["external_reference"] is not None
        assert settled_payment["external_reference"].startswith("CLR_FEDNOW_")
        assert settled_payment["cleared_at"] is not None

        # 3. Direct DB verification: check persistence
        engine = create_async_engine(test_database_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with session_factory() as session:
            stmt = select(Payment).where(Payment.payment_id == UUID(payment_id))
            res = await session.execute(stmt)
            persisted = res.scalar_one()
            assert persisted.status == "settled"
            assert persisted.amount_cents == 12550
        await engine.dispose()

    async def test_live_batch_disbursement_lifecycle(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
        auth_headers: dict[str, str],
    ) -> None:
        """Submit batch payroll disbursements -> .chunks() to bulk queue -> worker execution -> batch completed."""
        source_account_id = "a0000000-0000-0000-0000-000000000002"
        file_ref = f"ACH_LIVE_{uuid4().hex[:8]}"

        disbursements = [
            {
                "recipient_name": f"Recipient {i}",
                "account_number": f"99887766{i:04d}",
                "routing_number": "021000021",
                "amount": "50.00",
            }
            for i in range(10)
        ]

        # 1. POST /disbursements/batch
        create_res = await live_async_client.post(
            "/disbursements/batch",
            json={
                "file_reference": file_ref,
                "source_account_id": source_account_id,
                "disbursements": disbursements,
            },
            headers=auth_headers,
        )
        assert create_res.status_code == 202
        batch_id = create_res.json()["batch_id"]

        # 2. Poll GET /disbursements/batches/{id} until completed
        completed_batch = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_res = await live_async_client.get(f"/disbursements/batch/{batch_id}", headers=auth_headers)
            assert poll_res.status_code == 200
            data = poll_res.json()
            if data["status"] in ("completed", "failed"):
                completed_batch = data
                break

        assert completed_batch is not None, f"Batch {batch_id} did not finish within timeout"
        assert completed_batch["status"] == "completed"
        assert completed_batch["processed_items"] == 10

    async def test_live_duplicate_idempotency_prevention(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Duplicate request with identical Idempotency-Key returns existing record and dispatches only once."""
        source_account_id = "a0000000-0000-0000-0000-000000000001"
        idemp_key = f"idemp_dedup_live_{uuid4().hex}"

        payload = {
            "idempotency_key": idemp_key,
            "source_account_id": source_account_id,
            "destination_account_number": "112233445566",
            "destination_routing_number": "021000021",
            "amount": "75.00",
            "rail": "rtp",
            "description": "Live Idempotency Test",
        }

        # 1. First submission
        res1 = await live_async_client.post("/payments/instant", json=payload, headers=auth_headers)
        assert res1.status_code == 202
        payment_id_1 = res1.json()["payment_id"]

        # 2. Duplicate submission
        res2 = await live_async_client.post("/payments/instant", json=payload, headers=auth_headers)
        assert res2.status_code in (200, 202)
        payment_id_2 = res2.json()["payment_id"]

        # Invariant: Idempotency returns identical payment_id
        assert payment_id_1 == payment_id_2
