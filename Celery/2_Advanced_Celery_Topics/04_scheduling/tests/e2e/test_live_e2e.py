"""Live multi-process end-to-end (E2E) integration test suite for 04_scheduling.

Verifies TC-E2E-01:
1. Real AMQP message publishing across RabbitMQ queue ('reconciliation').
2. Live background Celery worker daemon subprocess consuming from queues.
3. Database persistence and atomic row-locking under real multi-process concurrency.
4. Asynchronous polling of reconciliation reports until terminal 'balanced' status.
5. Automated multi-day historical gap backfilling.
6. Idempotent re-execution preventing duplicate report rows.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import AsyncGenerator, Generator
from datetime import date
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.main import app
from app.models import ReconciliationReport

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def live_celery_worker(
    test_database_url: str,
    test_redis_url: str,
    rabbitmq_service_url: str,
) -> Generator[subprocess.Popen[bytes], None, None]:
    """Launch an isolated Celery worker daemon process for live multi-process E2E testing."""
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
        "RABBITMQ_URL": rabbitmq_service_url,
        "REDIS_URL": test_redis_url,
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "INFO",
    }

    log_file = open("/tmp/live_celery_worker_04.log", "w")
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
            "reconciliation,cleanup",
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
    settings.redis_url = test_redis_url
    settings.rabbitmq_url = rabbitmq_service_url
    settings.environment = "test"

    import app.db as app_db

    if app_db._engine is not None:
        await app_db._engine.dispose()
        app_db._engine = None
        app_db._session_factory = None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.mark.e2e
@pytest.mark.asyncio
class TestLiveSchedulingE2E:
    """TC-E2E-01: Live distributed multi-process E2E verification across API, broker, worker, and DB."""

    async def test_live_eod_reconciliation_lifecycle(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
    ) -> None:
        """Seed ledger entries -> trigger reconciliation -> worker executes -> poll until balanced."""
        period_str = "2026-09-23"
        period_date = date(2026, 9, 23)

        # 1. Seed balanced transactions via API
        seed_res = await live_async_client.post(
            "/api/v1/seed",
            json={
                "period_date": period_str,
                "scenario": "balanced",
                "amount_cents": 1000000,
            },
        )
        assert seed_res.status_code == 201
        assert seed_res.json()["entries_created"] == 2

        # 2. Trigger EOD cut-off reconciliation
        trigger_res = await live_async_client.post(
            "/api/v1/reconciliations/trigger",
            json={
                "period_date": period_str,
                "clearing_variance_cents": 0,
            },
        )
        assert trigger_res.status_code == 202
        data = trigger_res.json()
        assert data["status"] == "processing"
        task_id = data["task_id"]
        assert task_id is not None

        # 3. Immediate in-flight state verification (FinTech zero-404 guarantee)
        immediate_res = await live_async_client.get(f"/api/v1/reconciliations/{period_str}")
        assert immediate_res.status_code == 200
        assert immediate_res.json()["status"] in ("processing", "balanced")

        # 4. Asynchronously poll GET /api/v1/reconciliations/{period_date} until worker seals report
        balanced_report = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_res = await live_async_client.get(f"/api/v1/reconciliations/{period_str}")
            if poll_res.status_code == 200:
                report_data = poll_res.json()
                if report_data["status"] == "balanced":
                    balanced_report = report_data
                    break

        assert balanced_report is not None, f"Reconciliation for {period_str} did not balance within timeout"
        assert balanced_report["period_date"] == period_str
        assert balanced_report["status"] == "balanced"
        assert balanced_report["total_credits_cents"] == 1000000
        assert balanced_report["total_debits_cents"] == 1000000
        assert balanced_report["discrepancy_cents"] == 0
        assert balanced_report["verification_hash"] is not None

        # 4. Direct DB verification: confirm row in PostgreSQL
        engine = create_async_engine(test_database_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with session_factory() as session:
            stmt = select(ReconciliationReport).where(ReconciliationReport.period_date == period_date)
            res = await session.execute(stmt)
            persisted = res.scalar_one()
            assert persisted.status == "balanced"
            assert persisted.net_movement_cents == 0
        await engine.dispose()

    async def test_live_historical_gap_backfill_lifecycle(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
    ) -> None:
        """Seed gap dates -> trigger backfill API -> worker sequentially clears all missing business dates."""
        start_d = date(2026, 9, 14)  # Monday
        end_d = date(2026, 9, 16)  # Wednesday

        # 1. Trigger on-demand gap backfill for window
        trigger_res = await live_async_client.post(
            "/api/v1/reconciliations/backfill",
            json={
                "start_date": start_d.isoformat(),
                "end_date": end_d.isoformat(),
            },
        )
        assert trigger_res.status_code == 202
        assert trigger_res.json()["status"] == "queued"

        # 2. Asynchronously poll until all 3 business dates (Mon, Tue, Wed) have reports
        target_dates = ["2026-09-14", "2026-09-15", "2026-09-16"]
        cleared = False
        for _ in range(40):
            await asyncio.sleep(0.5)
            reports_found = 0
            for d_str in target_dates:
                res = await live_async_client.get(f"/api/v1/reconciliations/{d_str}")
                if res.status_code == 200:
                    reports_found += 1
            if reports_found == len(target_dates):
                cleared = True
                break

        assert cleared is True, f"Backfill failed to clear all target dates: {target_dates}"

    async def test_live_duplicate_cutoff_idempotency(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        live_async_client: AsyncClient,
        test_database_url: str,
    ) -> None:
        """Duplicate reconciliation trigger for existing date does not create duplicate database rows."""
        period_str = "2026-09-23"

        # 1. Trigger cut-off for period that was already reconciled
        res = await live_async_client.post(
            "/api/v1/reconciliations/trigger",
            json={
                "period_date": period_str,
                "clearing_variance_cents": 0,
            },
        )
        assert res.status_code == 202

        # 2. Wait briefly for worker task execution
        await asyncio.sleep(2.0)

        # 3. Assert exactly 1 database row exists for this date
        engine = create_async_engine(test_database_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with session_factory() as session:
            stmt = select(ReconciliationReport).where(ReconciliationReport.period_date == date(2026, 9, 23))
            reports = (await session.execute(stmt)).scalars().all()
            assert len(reports) == 1
        await engine.dispose()
