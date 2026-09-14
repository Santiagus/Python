"""End-to-end (E2E) tests across the live distributed architecture.

Tests the full stack over live infrastructure:
- Live RabbitMQ message broker
- Live Redis result backend and chord barrier
- Live Celery worker process pool
- Live PostgreSQL database persistence
- FastAPI HTTP async client
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import os
import subprocess
import sys
import time
from collections.abc import Generator
from uuid import UUID

import pytest
from httpx import AsyncClient
import redis
import amqp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, UnderwritingMemo
from services.worker.celery_app import celery_app


@pytest.fixture(scope="module")
def live_celery_worker(
    test_database_url: str,
    rabbitmq_service_url: str,
    redis_service_url: str,
) -> Generator[subprocess.Popen[bytes], None, None]:
    """Launch an isolated Celery worker daemon process for live E2E testing."""
    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    orig_broker = celery_app.conf.broker_url
    orig_backend = celery_app.conf.result_backend

    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
        broker_url=rabbitmq_service_url,
        result_backend=redis_service_url,
    )

    worker_env = {
        **os.environ,
        "DATABASE_URL": test_database_url,
        "RABBITMQ_URL": rabbitmq_service_url,
        "REDIS_URL": redis_service_url,
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
            "--loglevel=WARNING",
        ],
        env=worker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    time.sleep(2.5)

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


@pytest.mark.asyncio
class TestLiveDistributedE2E:
    """Live distributed end-to-end tests verifying async API, broker, worker, and database."""

    async def test_live_e2e_happy_path_application_approval(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        async_client: AsyncClient,
        db_session: AsyncSession,
        clean_dossier_manifest: dict[str, str],
    ) -> None:
        """Full live lifecycle: Ingest -> RabbitMQ -> Worker Chord -> Redis Barrier -> DB Memo -> Polling."""
        # 1. POST /applications (FastAPI -> PostgreSQL)
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Apex Fintech Dynamics Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 250000.00,
            },
        )
        assert create_resp.status_code == 201
        app_id = create_resp.json()["application_id"]

        # 2. POST /applications/{id}/dossier (Dispatches workflow across real RabbitMQ to Worker)
        dossier_resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert dossier_resp.status_code == 202
        assert "workflow_id" in dossier_resp.json()

        # 3. Asynchronously poll GET /applications/{id} until worker completes and status is terminal
        final_payload = None
        max_attempts = 30
        for _ in range(max_attempts):
            await asyncio.sleep(0.5)
            poll_resp = await async_client.get(f"/api/v1/applications/{app_id}")
            assert poll_resp.status_code == 200
            data = poll_resp.json()
            if data["status"] in ("approved", "declined", "manual_review", "failed"):
                final_payload = data
                break

        assert final_payload is not None, f"Workflow timed out for application {app_id}"
        assert final_payload["status"] == "approved"
        assert Decimal(final_payload["requested_facility"]) == Decimal("250000.00")
        assert final_payload["underwriting_memo"] is not None
        assert final_payload["underwriting_memo"]["decision"] == "approved"
        assert Decimal(final_payload["underwriting_memo"]["calculated_dscr"]) == Decimal("3.250")
        assert Decimal(final_payload["underwriting_memo"]["net_cashflow"]) == Decimal("32549.50")
        assert Decimal(final_payload["underwriting_memo"]["total_revenue"]) == Decimal("1450000.00")

        # 4. Verify PostgreSQL persistence directly
        memo_stmt = select(UnderwritingMemo).where(UnderwritingMemo.application_id == UUID(app_id))
        memo = (await db_session.execute(memo_stmt)).scalar_one_or_none()
        assert memo is not None
        assert memo.decision == "approved"
        assert memo.net_cashflow == Decimal("32549.50")
        assert memo.total_revenue == Decimal("1450000.00")

        # 5. Verify timing telemetry from live chord execution
        timing_resp = await async_client.get(f"/api/v1/applications/{app_id}/timing")
        assert timing_resp.status_code == 200
        timing = timing_resp.json()
        assert timing["stage_1_validation_ms"] > 0
        assert timing["stage_2_fanout_chord_ms"] > 0
        assert timing["stage_3_fanin_aggregation_ms"] > 0
        assert timing["total_pipeline_ms"] > 0

    async def test_live_e2e_degraded_dossier_manual_review(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        async_client: AsyncClient,
        degraded_dossier_manifest: dict[str, str],
    ) -> None:
        """Degraded statement page in live chord leads to manual_review status."""
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Degraded OCR Corp",
                "applicant_name": "JANE DOE",
                "requested_facility": 180000.00,
            },
        )
        assert create_resp.status_code == 201
        app_id = create_resp.json()["application_id"]

        dossier_resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": degraded_dossier_manifest},
        )
        assert dossier_resp.status_code == 202

        final_payload = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_resp = await async_client.get(f"/api/v1/applications/{app_id}")
            data = poll_resp.json()
            if data["status"] in ("approved", "declined", "manual_review", "failed"):
                final_payload = data
                break

        assert final_payload is not None
        assert final_payload["status"] == "manual_review"
        assert final_payload["underwriting_memo"]["decision"] == "manual_review"
        assert any("degraded" in flag.lower() or "ocr" in flag.lower() for flag in final_payload["underwriting_memo"]["audit_flags"])

    async def test_live_e2e_corrupted_dossier_failure_errback(
        self,
        live_celery_worker: subprocess.Popen[bytes],
        async_client: AsyncClient,
        corrupted_dossier_manifest: dict[str, str],
    ) -> None:
        """Corrupted statement triggers link_error errback to transition application to failed."""
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Corrupt Statement Corp",
                "applicant_name": "JOHN DOE",
                "requested_facility": 100000.00,
            },
        )
        assert create_resp.status_code == 201
        app_id = create_resp.json()["application_id"]

        dossier_resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": corrupted_dossier_manifest},
        )
        assert dossier_resp.status_code == 202

        final_payload = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_resp = await async_client.get(f"/api/v1/applications/{app_id}")
            data = poll_resp.json()
            if data["status"] in ("approved", "declined", "manual_review", "failed"):
                final_payload = data
                break

        assert final_payload is not None
        assert final_payload["status"] == "failed"
        assert final_payload["error_message"] is not None
        assert "corrupt" in final_payload["error_message"].lower() or "invalid" in final_payload["error_message"].lower()
