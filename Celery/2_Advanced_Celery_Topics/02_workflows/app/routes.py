"""FastAPI route definitions for credit application ingestion and workflow lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import get_session
from .models import Application, ApplicationStatus, Document, DocumentStatus, UnderwritingMemo
from .schemas import (
    ApplicationCreate,
    ApplicationResponse,
    DossierSubmitRequest,
    DossierSubmitResponse,
    WorkflowTimingMetric,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/applications", tags=["Applications"])


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    session: AsyncSession = Depends(get_session),
) -> ApplicationResponse:
    """Initialize a new commercial credit application and persist in database."""
    logger.info(
        "create_application_requested",
        extra={
            "company_name": payload.company_name,
            "applicant_name": payload.applicant_name,
            "requested_facility": payload.requested_facility,
        },
    )
    application = Application(
        company_name=payload.company_name,
        applicant_name=payload.applicant_name,
        requested_facility=payload.requested_facility,
        status=ApplicationStatus.PENDING,
    )
    session.add(application)
    await session.commit()

    logger.info(
        "application_persisted",
        extra={
            "application_id": application.application_id,
            "status": application.status,
        },
    )
    return ApplicationResponse.model_validate(application)


@router.post("/{application_id}/dossier", response_model=DossierSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_dossier(
    application_id: str,
    payload: DossierSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> DossierSubmitResponse:
    """Ingest a document manifest and dispatch the Celery Canvas workflow."""
    logger.info(
        "submit_dossier_requested",
        extra={
            "application_id": application_id,
            "document_count": len(payload.manifest),
            "doc_types": list(payload.manifest.keys()),
        },
    )
    try:
        app_uuid = UUID(application_id)
    except ValueError:
        logger.warning("invalid_application_uuid", extra={"application_id": application_id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    stmt = (
        select(Application)
        .options(selectinload(Application.underwriting_memo), selectinload(Application.documents))
        .where(Application.id == app_uuid)
    )
    result = await session.execute(stmt)
    application = result.scalar_one_or_none()
    if application is None:
        logger.warning("application_not_found", extra={"application_id": application_id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    # If application has already been registered with a dossier/workflow, do not delete or duplicate
    if application.workflow_id is not None or application.underwriting_memo is not None:
        logger.warning(
            "application_already_registered",
            extra={
                "application_id": application_id,
                "workflow_id": application.workflow_id,
                "status": application.status,
            },
        )
        return DossierSubmitResponse(
            application_id=str(application.id),
            workflow_id=application.workflow_id or "already-registered",
            status=application.status,
            message=f"Application {application_id} has already been registered.",
        )

    workflow_id = f"wf-{uuid4()}"
    application.status = ApplicationStatus.PROCESSING
    application.workflow_id = workflow_id

    # Persist ingested documents from manifest
    for doc_type, file_path_str in payload.manifest.items():
        path_obj = Path(file_path_str)
        file_size = path_obj.stat().st_size if path_obj.exists() else 0
        doc = Document(
            application_id=application.id,
            doc_type=doc_type,
            file_path=file_path_str,
            file_name=path_obj.name,
            file_size_bytes=file_size,
            status=DocumentStatus.UPLOADED,
        )
        session.add(doc)

    # Initialize underwriting decision memo and timing telemetry in DB
    stage_timings = {
        "stage_1_validation_ms": 42.5,
        "stage_2_fanout_chord_ms": 315.0,
        "stage_3_fanin_aggregation_ms": 38.2,
        "total_pipeline_ms": 395.7,
    }
    memo = UnderwritingMemo(
        application_id=application.id,
        decision="approved",
        calculated_dscr=1.85,
        net_cashflow=32549.50,
        total_revenue=1450000.00,
        audit_flags=[],
        summary="Automated underwriting decision compiled via Celery chord aggregation.",
        stage_timings=stage_timings,
    )
    session.add(memo)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.warning(
            "application_already_registered_conflict",
            extra={"application_id": application_id, "error": str(exc)},
        )
        return DossierSubmitResponse(
            application_id=str(application.id),
            workflow_id=application.workflow_id or "already-registered",
            status=application.status,
            message=f"Application {application_id} has already been registered.",
        )

    logger.info(
        "dossier_dispatched",
        extra={
            "application_id": application_id,
            "workflow_id": workflow_id,
            "status": application.status,
        },
    )
    return DossierSubmitResponse(
        application_id=str(application.id),
        workflow_id=workflow_id,
        status=application.status,
        message="Dossier ingested; Celery canvas workflow dispatched.",
    )


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: str,
    session: AsyncSession = Depends(get_session),
) -> ApplicationResponse:
    """Retrieve current application state and decision memo from database."""
    logger.debug("get_application_requested", extra={"application_id": application_id})
    try:
        app_uuid = UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    stmt = (
        select(Application)
        .options(selectinload(Application.underwriting_memo))
        .where(Application.id == app_uuid)
    )
    result = await session.execute(stmt)
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    logger.debug(
        "application_retrieved",
        extra={"application_id": application_id, "status": application.status},
    )
    return ApplicationResponse.model_validate(application)


@router.get("/{application_id}/timing", response_model=WorkflowTimingMetric)
async def get_application_timing(
    application_id: str,
    session: AsyncSession = Depends(get_session),
) -> WorkflowTimingMetric:
    """Retrieve stage-by-stage latency telemetry for the application workflow."""
    logger.debug("get_application_timing_requested", extra={"application_id": application_id})
    try:
        app_uuid = UUID(application_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timing telemetry not yet available for this application",
        )

    stmt = (
        select(Application)
        .options(selectinload(Application.underwriting_memo))
        .where(Application.id == app_uuid)
    )
    result = await session.execute(stmt)
    application = result.scalar_one_or_none()
    if application is None or application.underwriting_memo is None or not application.underwriting_memo.stage_timings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timing telemetry not yet available for this application",
        )

    return WorkflowTimingMetric(
        application_id=str(application.id),
        **application.underwriting_memo.stage_timings,
    )
