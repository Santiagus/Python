"""Tests for FastAPI ingestion endpoints and workflow lifecycle API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestApplicationAPI:
    """Test REST API application endpoints."""

    async def test_create_application(self, async_client: AsyncClient) -> None:
        """Verify initialization of a credit facility application."""
        response = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Apex Fintech Dynamics Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 250000.00,
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert "application_id" in payload
        assert payload["status"] == "pending"
        assert payload["company_name"] == "Apex Fintech Dynamics Inc."

    async def test_submit_dossier_and_poll_status(
        self, async_client: AsyncClient, clean_dossier_manifest: dict[str, str]
    ) -> None:
        """Verify submitting dossier files triggers workflow and status polling reflects progress."""
        # 1. Create application
        create_resp = await async_client.post(
            "/api/v1/applications",
            json={
                "company_name": "Apex Fintech Dynamics Inc.",
                "applicant_name": "JANE DOE",
                "requested_facility": 250000.00,
            },
        )
        app_id = create_resp.json()["application_id"]

        # 2. Submit dossier manifest
        dossier_resp = await async_client.post(
            f"/api/v1/applications/{app_id}/dossier",
            json={"manifest": clean_dossier_manifest},
        )
        assert dossier_resp.status_code == 202
        assert "workflow_id" in dossier_resp.json()

        # 3. Poll application status
        status_resp = await async_client.get(f"/api/v1/applications/{app_id}")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["application_id"] == app_id

        # 4. Query timing telemetry
        timing_resp = await async_client.get(f"/api/v1/applications/{app_id}/timing")
        assert timing_resp.status_code in (200, 404)
