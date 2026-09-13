"""Integration tests for FastAPI endpoints interacting with PostgreSQL via Testcontainers."""

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

        # 2. Submit dossier manifest via POST /applications/{id}/dossier
        dossier_resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert dossier_resp.status_code == 202
        dossier_payload = dossier_resp.json()
        assert dossier_payload["application_id"] == app_id
        assert dossier_payload["status"] == "processing"
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
        assert float(memo.calculated_dscr) == 1.85

        # 3. Retrieve application state via GET /applications/{id}
        get_resp = await async_client.get(f"/api/v1/applications/{app_id}")
        assert get_resp.status_code == 200
        get_payload = get_resp.json()
        assert get_payload["application_id"] == app_id
        assert get_payload["status"] == "processing"
        assert get_payload["underwriting_memo"] is not None
        assert get_payload["underwriting_memo"]["decision"] == "approved"
        assert get_payload["underwriting_memo"]["calculated_dscr"] == 1.85
        assert get_payload["underwriting_memo"]["net_cashflow"] == 32549.50

        # 4. Retrieve latency timing telemetry via GET /applications/{id}/timing
        timing_resp = await async_client.get(f"/api/v1/applications/{app_id}/timing")
        assert timing_resp.status_code == 200
        timing_payload = timing_resp.json()
        assert timing_payload["application_id"] == app_id
        assert timing_payload["stage_1_validation_ms"] == 42.5
        assert timing_payload["stage_2_fanout_chord_ms"] == 315.0
        assert timing_payload["stage_3_fanin_aggregation_ms"] == 38.2
        assert timing_payload["total_pipeline_ms"] == 395.7

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
        assert resp1.json()["status"] == "processing"

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
