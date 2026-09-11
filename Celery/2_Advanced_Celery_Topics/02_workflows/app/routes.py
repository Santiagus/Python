"""FastAPI route definitions for credit application ingestion and workflow lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from fastapi import APIRouter, HTTPException, status

from .schemas import (
    ApplicationCreate,
    ApplicationResponse,
    DossierSubmitRequest,
    DossierSubmitResponse,
    UnderwritingDecisionSummary,
    WorkflowTimingMetric,
)

router = APIRouter(prefix="/applications", tags=["Applications"])

# In-memory storage dictionary for static/mocked lifecycle states
_APPLICATIONS_DB: dict[str, dict[str, Any]] = {}
_TIMINGS_DB: dict[str, dict[str, Any]] = {}


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(payload: ApplicationCreate) -> ApplicationResponse:
    """Initialize a new commercial credit application."""
    app_id = str(uuid4())
    now = datetime.now(timezone.utc)
    app_record = {
        "application_id": app_id,
        "company_name": payload.company_name,
        "applicant_name": payload.applicant_name,
        "requested_facility": payload.requested_facility,
        "status": "pending",
        "workflow_id": None,
        "error_message": None,
        "underwriting_memo": None,
        "created_at": now,
        "updated_at": now,
    }
    _APPLICATIONS_DB[app_id] = app_record
    return ApplicationResponse(**app_record)


@router.post("/{application_id}/dossier", response_model=DossierSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_dossier(application_id: str, payload: DossierSubmitRequest) -> DossierSubmitResponse:
    """Ingest a document manifest and dispatch the Celery Canvas workflow."""
    if application_id not in _APPLICATIONS_DB:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    workflow_id = f"wf-{uuid4()}"
    app_record = _APPLICATIONS_DB[application_id]
    app_record["status"] = "processing"
    app_record["workflow_id"] = workflow_id
    app_record["updated_at"] = datetime.now(timezone.utc)

    # Populate mock decision memo and telemetry metrics
    app_record["underwriting_memo"] = UnderwritingDecisionSummary(
        decision="approved",
        calculated_dscr=1.85,
        net_cashflow=32549.50,
        total_revenue=1450000.00,
        audit_flags=[],
        summary="Automated underwriting decision compiled via Celery chord aggregation.",
    )

    _TIMINGS_DB[application_id] = {
        "application_id": application_id,
        "stage_1_validation_ms": 42.5,
        "stage_2_fanout_chord_ms": 315.0,
        "stage_3_fanin_aggregation_ms": 38.2,
        "total_pipeline_ms": 395.7,
    }

    return DossierSubmitResponse(
        application_id=application_id,
        workflow_id=workflow_id,
        status="processing",
    )


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(application_id: str) -> ApplicationResponse:
    """Retrieve current application state and decision memo."""
    if application_id not in _APPLICATIONS_DB:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    return ApplicationResponse(**_APPLICATIONS_DB[application_id])


@router.get("/{application_id}/timing", response_model=WorkflowTimingMetric)
async def get_application_timing(application_id: str) -> WorkflowTimingMetric:
    """Retrieve stage-by-stage latency telemetry for the application workflow."""
    if application_id not in _TIMINGS_DB:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timing telemetry not yet available for this application",
        )

    return WorkflowTimingMetric(**_TIMINGS_DB[application_id])

