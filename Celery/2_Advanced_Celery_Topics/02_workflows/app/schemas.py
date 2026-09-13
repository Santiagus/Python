"""Pydantic request and response schemas for credit application ingestion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApplicationCreate(BaseModel):
    """Payload for initializing a commercial credit application."""

    company_name: str = Field(..., description="Legal commercial entity name", examples=["Apex Fintech Dynamics Inc."])
    applicant_name: str = Field(..., description="Authorized executive full name", examples=["JANE DOE"])
    requested_facility: float = Field(..., gt=0, description="Requested facility principal amount in USD", examples=[250000.00])


class DossierSubmitRequest(BaseModel):
    """Payload for submitting dossier document manifest."""

    manifest: dict[str, str] = Field(
        ...,
        description="Dictionary mapping doc_type ('bank_statement', 'kyc_id', 'tax_filing') to file paths",
    )


class DossierSubmitResponse(BaseModel):
    """Response confirming dossier receipt and Celery workflow dispatch."""

    application_id: str
    workflow_id: str
    status: str
    message: str = "Dossier ingested; Celery canvas workflow dispatched."


class UnderwritingDecisionSummary(BaseModel):
    """Summary of compiled underwriting memo."""

    model_config = ConfigDict(from_attributes=True)

    decision: str = Field(..., description="'approved', 'declined', or 'manual_review'")
    calculated_dscr: float | None = None
    net_cashflow: float | None = None
    total_revenue: float | None = None
    audit_flags: list[Any] = Field(default_factory=list)
    summary: str


class ApplicationResponse(BaseModel):
    """Full application state response for client polling."""

    model_config = ConfigDict(from_attributes=True)

    application_id: str
    company_name: str
    applicant_name: str
    requested_facility: float
    status: str
    workflow_id: str | None = None
    error_message: str | None = None
    underwriting_memo: UnderwritingDecisionSummary | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowTimingMetric(BaseModel):
    """Stage-by-stage latency telemetry for the Celery canvas execution."""

    application_id: str
    stage_1_validation_ms: float
    stage_2_fanout_chord_ms: float
    stage_3_fanin_aggregation_ms: float
    total_pipeline_ms: float
