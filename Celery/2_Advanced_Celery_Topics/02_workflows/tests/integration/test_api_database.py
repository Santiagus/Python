"""Integration tests for FastAPI endpoints interacting with PostgreSQL via Testcontainers."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Document, UnderwritingMemo


@pytest.mark.asyncio
class TestApiDatabaseIntegration:
    """End-to-end integration tests for REST API with real PostgreSQL persistence."""

    async def test_full_application_lifecycle_with_db(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        clean_dossier_manifest: dict[str, str],
    ) -> None:
        """Verify application creation, dossier submission, DB persistence, and status polling."""
        # 1. Create Application via POST /applications
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Apex Fintech Dynamics Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 250000.00,
            },
        )
        assert create_resp.status_code == 201
        created_payload = create_resp.json()
        app_id = created_payload["application_id"]
        assert created_payload["status"] == "pending"
        assert created_payload["company_name"] == "Apex Fintech Dynamics Inc."

        # Verify record exists in PostgreSQL
        stmt = select(Application).where(Application.id == UUID(app_id))
        db_app = (await db_session.execute(stmt)).scalar_one_or_none()
        assert db_app is not None
        assert db_app.applicant_name == "JANE DOE"
        assert float(db_app.requested_facility) == 250000.00
        assert db_app.requested_facility == Decimal("250000.00")
        assert db_app.requested_facility_cents == 25000000

        # 2. Submit dossier manifest via POST /applications/{id}/dossier
        dossier_resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert dossier_resp.status_code == 202
        dossier_payload = dossier_resp.json()
        assert dossier_payload["application_id"] == app_id
        assert dossier_payload["status"] in ("pending", "validating", "processing", "approved")
        assert "workflow_id" in dossier_payload

        # Verify documents persisted to PostgreSQL documents table
        doc_stmt = select(Document).where(Document.application_id == db_app.id)
        docs = (await db_session.execute(doc_stmt)).scalars().all()
        assert len(docs) == 3
        doc_types = {d.doc_type for d in docs}
        assert doc_types == {"bank_statement", "kyc_id", "tax_filing"}

        # Verify underwriting memo was persisted
        memo_stmt = select(UnderwritingMemo).where(UnderwritingMemo.application_id == db_app.id)
        memo = (await db_session.execute(memo_stmt)).scalar_one_or_none()
        assert memo is not None
        assert memo.decision == "approved"
        assert memo.calculated_dscr == Decimal("3.250")
        assert memo.net_cashflow == Decimal("32549.50")
        assert memo.net_cashflow_cents == 3254950
        assert memo.total_revenue == Decimal("1450000.00")
        assert memo.total_revenue_cents == 145000000

        # 3. Retrieve application state via GET /applications/{id}
        get_resp = await async_client.get(f"/api/v1/applications/{app_id}")
        assert get_resp.status_code == 200
        get_payload = get_resp.json()
        assert get_payload["application_id"] == app_id
        assert get_payload["status"] == "approved"
        assert Decimal(get_payload["requested_facility"]) == Decimal("250000.00")
        assert get_payload["underwriting_memo"] is not None
        assert get_payload["underwriting_memo"]["decision"] == "approved"
        assert Decimal(get_payload["underwriting_memo"]["calculated_dscr"]) == Decimal("3.250")
        assert Decimal(get_payload["underwriting_memo"]["net_cashflow"]) == Decimal("32549.50")
        assert Decimal(get_payload["underwriting_memo"]["total_revenue"]) == Decimal("1450000.00")

        # 4. Retrieve latency timing telemetry via GET /applications/{id}/timing
        timing_resp = await async_client.get(f"/api/v1/applications/{app_id}/timing")
        assert timing_resp.status_code == 200
        timing_payload = timing_resp.json()
        assert timing_payload["application_id"] == app_id
        assert timing_payload["stage_1_validation_ms"] > 0
        assert timing_payload["stage_2_fanout_chord_ms"] > 0
        assert timing_payload["stage_3_fanin_aggregation_ms"] > 0
        assert timing_payload["total_pipeline_ms"] > 0
        assert timing_payload["total_pipeline_ms"] >= (
            timing_payload["stage_1_validation_ms"] + timing_payload["stage_3_fanin_aggregation_ms"]
        )

    async def test_get_nonexistent_application_returns_404(self, async_client: AsyncClient) -> None:
        """Non-existent or malformed application UUID must return 404."""
        random_uuid = str(uuid4())
        resp = await async_client.get(f"/api/v1/applications/{random_uuid}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Application not found"

        invalid_resp = await async_client.get("/api/v1/applications/not-a-uuid")
        assert invalid_resp.status_code == 404
        assert invalid_resp.json()["detail"] == "Application not found"

    async def test_submit_dossier_nonexistent_application_returns_404(
        self, async_client: AsyncClient
    ) -> None:
        """Submitting dossier for non-existent application must return 404."""
        random_uuid = str(uuid4())
        resp = await async_client.post(
            f"/api/v1/applications/{random_uuid}/dossier",
            json={"manifest": {"kyc_id": "/tmp/test.jpg"}},
        )
        assert resp.status_code == 404

    async def test_create_application_validation_error_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        """Invalid application payload must return 422 Unprocessable Entity."""
        resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Invalid Corp",
                "applicant_name": "Test User",
                "requested_facility": -5000.0,
            },
        )
        assert resp.status_code == 422

    async def test_resubmit_dossier_returns_already_registered_message(
        self,
        async_client: AsyncClient,
        clean_dossier_manifest: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Submitting a dossier a second time returns an already registered message without deleting docs."""
        # 1. Create Application
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Duplicate Test Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 100000.00,
            },
        )
        app_id = create_resp.json()["application_id"]

        # 2. Submit dossier first time
        resp1 = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert resp1.status_code == 202
        assert resp1.json()["status"] in ("pending", "validating", "processing", "approved")

        # 3. Submit dossier second time
        resp2 = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert resp2.status_code == 202
        payload = resp2.json()
        assert "already been registered" in payload["message"]

        # 4. Verify previous documents were preserved (not deleted)
        doc_stmt = select(func.count(Document.id)).where(Document.application_id == UUID(app_id))
        doc_count = (await db_session.execute(doc_stmt)).scalar()
        assert doc_count == 3

    async def test_submit_dossier_invalid_uuid_returns_404(
        self, async_client: AsyncClient, clean_dossier_manifest: dict[str, str]
    ) -> None:
        """Submitting dossier with malformed UUID returns 404."""
        resp = await async_client.post(
            "/api/v1/applications/not-a-valid-uuid/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Application not found"

    async def test_submit_dossier_dispatch_error_fallback(
        self,
        async_client: AsyncClient,
        clean_dossier_manifest: dict[str, str],
        monkeypatch,
    ) -> None:
        """When Celery dispatch raises an exception, route falls back gracefully to generated workflow_id."""
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Dispatch Error Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 150000.00,
            },
        )
        app_id = create_resp.json()["application_id"]

        def mock_dispatch_fail(*args, **kwargs):
            raise ConnectionError("RabbitMQ broker connection refused")

        import app.tasks
        monkeypatch.setattr(app.tasks, "dispatch_underwriting_workflow", mock_dispatch_fail)

        resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert resp.status_code == 202
        payload = resp.json()
        assert payload["workflow_id"].startswith("wf-")

    async def test_create_application_dispatch_error_fallback(
        self,
        async_client: AsyncClient,
        clean_dossier_manifest: dict[str, str],
        monkeypatch,
    ) -> None:
        """Single-step application creation falls back to synthetic workflow_id if broker is unavailable."""
        def mock_dispatch_fail(*args, **kwargs):
            raise ConnectionError("RabbitMQ broker connection refused")

        import app.tasks
        monkeypatch.setattr(app.tasks, "dispatch_underwriting_workflow", mock_dispatch_fail)

        resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Create Error Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 120000.00,
                "manifest": clean_dossier_manifest,
            },
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["workflow_id"].startswith("wf-")

    async def test_submit_dossier_integrity_error_rollback(
        self,
        async_client: AsyncClient,
        clean_dossier_manifest: dict[str, str],
        monkeypatch,
    ) -> None:
        """When DB commit encounters an IntegrityError conflict, it rolls back and returns already registered."""
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Integrity Conflict Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 180000.00,
            },
        )
        app_id = create_resp.json()["application_id"]

        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import AsyncSession

        original_commit = AsyncSession.commit

        async def mock_commit(session_self):
            raise IntegrityError("duplicate key value violates unique constraint", params=None, orig=Exception())

        monkeypatch.setattr(AsyncSession, "commit", mock_commit)

        resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert resp.status_code == 202
        payload = resp.json()
        assert "already been registered" in payload["message"]

    async def test_timing_telemetry_edge_cases_404(
        self, async_client: AsyncClient
    ) -> None:
        """Timing endpoint returns 404 for invalid UUID, non-existent app, and app without memo."""
        # 1. Invalid UUID
        invalid_resp = await async_client.get("/api/v1/applications/invalid-uuid/timing")
        assert invalid_resp.status_code == 404
        assert "Timing telemetry not yet available" in invalid_resp.json()["detail"]

        # 2. Non-existent app
        non_existent_id = str(uuid4())
        non_existent_resp = await async_client.get(f"/api/v1/applications/{non_existent_id}/timing")
        assert non_existent_resp.status_code == 404

        # 3. Application exists but no dossier/memo submitted
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "No Memo Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 100000.00,
            },
        )
        app_id = create_resp.json()["application_id"]
        no_memo_resp = await async_client.get(f"/api/v1/applications/{app_id}/timing")
        assert no_memo_resp.status_code == 404

    async def test_single_step_application_creation_with_manifest(
        self,
        async_client: AsyncClient,
        clean_dossier_manifest: dict[str, str],
    ) -> None:
        """Verify single-step application creation with embedded manifest dispatches workflow and persists timing."""
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Fast Track Lending LLC",
                "applicant_name": "JANE DOE",
                "requested_facility": 300000.00,
                "manifest": clean_dossier_manifest,
            },
        )
        assert create_resp.status_code == 201
        created_payload = create_resp.json()
        app_id = created_payload["application_id"]
        assert created_payload["company_name"] == "Fast Track Lending LLC"

        # Polling status returns memo
        get_resp = await async_client.get(f"/api/v1/applications/{app_id}")
        assert get_resp.status_code == 200
        get_payload = get_resp.json()
        assert get_payload["underwriting_memo"] is not None
        assert get_payload["underwriting_memo"]["decision"] == "approved"

        # Telemetry returns real timings > 0
        timing_resp = await async_client.get(f"/api/v1/applications/{app_id}/timing")
        assert timing_resp.status_code == 200
        timing_payload = timing_resp.json()
        assert timing_payload["application_id"] == app_id
        assert timing_payload["stage_1_validation_ms"] > 0
        assert timing_payload["stage_2_fanout_chord_ms"] > 0
        assert timing_payload["stage_3_fanin_aggregation_ms"] > 0
        assert timing_payload["total_pipeline_ms"] > 0

