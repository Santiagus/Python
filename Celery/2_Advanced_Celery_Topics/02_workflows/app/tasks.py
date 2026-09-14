"""Celery client workflow builder and dispatcher for credit underwriting.

Constructs and dispatches the multi-stage Celery Canvas graph:
1. Sequential Gatekeeper (validate_dossier) with link_error errback
2. Parallel Chord Header (process_kyc_document, process_tax_return, process_bank_statement_page)
3. Fan-in Synthesis Callback (aggregate_underwriting_decision)
"""

from __future__ import annotations

from decimal import Decimal
import logging
import time
from typing import Any
from uuid import uuid4

from celery import chord
from celery.result import AsyncResult

from services.worker.celery_app import celery_app
from services.worker.tasks import (
    _update_application_status,
    aggregate_underwriting_decision,
    handle_workflow_failure,
    process_bank_statement_page,
    process_kyc_document,
    process_tax_return,
    validate_dossier,
)

logger = logging.getLogger(__name__)


def build_underwriting_chord(
    application_id: str,
    manifest: dict[str, str],
    applicant_name: str,
    requested_facility: Decimal | int | float | str,
    page_ids: list[str],
    stage_1_validation_ms: float = 0.0,
    chord_dispatched_at: float | None = None,
) -> Any:
    """Construct the parallel chord canvas stage for an underwriting dossier.

    Args:
        application_id: Credit application UUID string.
        manifest: Mapping of document types to storage file paths.
        applicant_name: Legal applicant name from application manifest.
        requested_facility: Dollar facility amount requested.
        page_ids: List of partitioned bank statement page UUID strings.
        stage_1_validation_ms: Real Stage 1 gatekeeper validation latency in ms.
        chord_dispatched_at: Timestamp when chord was dispatched for Stage 2 telemetry.

    Returns:
        Celery chord signature ready for execution.
    """
    statement_path = manifest.get("bank_statement", "")
    header = [
        process_kyc_document.s(application_id, manifest.get("kyc_id", ""), applicant_name),
        process_tax_return.s(application_id, manifest.get("tax_filing", "")),
        *[
            process_bank_statement_page.s(application_id, pid, pnum, statement_path)
            for pnum, pid in enumerate(page_ids, start=1)
        ],
    ]

    callback = aggregate_underwriting_decision.s(
        application_id,
        requested_facility,
        stage_1_validation_ms,
        chord_dispatched_at,
    )
    return chord(header, callback)


def dispatch_underwriting_workflow(
    application_id: str,
    manifest: dict[str, str],
    applicant_name: str,
    requested_facility: Decimal | int | float | str,
) -> AsyncResult:
    """Execute Stage 1 gatekeeper validation and dispatch Stage 2 & 3 parallel chord.

    If validation fails (e.g. corrupt PDF), the attached link_error errback
    routes to handle_workflow_failure and returns the failed task result.

    Args:
        application_id: Credit application UUID string.
        manifest: Mapping of document types to file paths.
        applicant_name: Name of applicant.
        requested_facility: Amount requested.

    Returns:
        AsyncResult tracking the dispatched workflow.
    """
    logger.info("Dispatching underwriting workflow for application %s", application_id)
    facility_dec = Decimal(str(requested_facility)) if not isinstance(requested_facility, Decimal) else requested_facility

    # Stage 1: Validate dossier with link_error errback attached
    t1_start = time.perf_counter()
    validation_sig = validate_dossier.s(
        application_id, manifest, applicant_name, facility_dec
    ).on_error(handle_workflow_failure.s(application_id))

    validation_res = validation_sig.apply()
    t1_end = time.perf_counter()
    if validation_res.failed():
        logger.warning("Dossier validation failed for %s", application_id)
        return validation_res

    validation_result = validation_res.get()
    page_ids = validation_result.get("page_ids", [])
    stage_1_ms = validation_result.get("validation_duration_ms") or max(
        round((t1_end - t1_start) * 1000, 2), 0.1
    )

    chord_start_time = time.time()

    # Stages 2 & 3: Parallel chord fan-out and fan-in aggregation
    workflow_chord = build_underwriting_chord(
        application_id=application_id,
        manifest=manifest,
        applicant_name=applicant_name,
        requested_facility=facility_dec,
        page_ids=page_ids,
        stage_1_validation_ms=stage_1_ms,
        chord_dispatched_at=chord_start_time,
    )

    _update_application_status(application_id, "processing")
    return workflow_chord.apply_async()
