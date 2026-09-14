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

from celery import chain, chord, group
from celery.result import AsyncResult

from services.worker.celery_app import celery_app
from services.worker.tasks import (
    _update_application_status,
    aggregate_underwriting_decision,
    audit_notification_task,
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
    logger.debug(
        "canvas_signature_s_created",
        extra={
            "primitive": ".s()",
            "application_id": application_id,
            "tasks": ["process_kyc_document", "process_tax_return"]
            + [f"process_bank_statement_page(p={pnum})" for pnum in range(1, len(page_ids) + 1)],
            "note": "Created mutable signatures (.s()) for chord header tasks",
        },
    )
    header = [
        process_kyc_document.s(application_id, manifest.get("kyc_id", ""), applicant_name),
        process_tax_return.s(application_id, manifest.get("tax_filing", "")),
        *[
            process_bank_statement_page.s(application_id, pid, pnum, statement_path)
            for pnum, pid in enumerate(page_ids, start=1)
        ],
    ]

    header_group = group(header)
    logger.debug(
        "canvas_group_created",
        extra={
            "primitive": "group",
            "application_id": application_id,
            "group_size": len(header),
            "note": "Assembled header tasks into parallel execution group",
        },
    )

    callback = aggregate_underwriting_decision.s(
        application_id,
        requested_facility,
        stage_1_validation_ms,
        chord_dispatched_at,
    )
    logger.debug(
        "canvas_signature_s_created",
        extra={
            "primitive": ".s()",
            "application_id": application_id,
            "task": "aggregate_underwriting_decision",
            "note": "Created mutable signature (.s()) for fan-in synthesis callback",
        },
    )

    workflow_chord = chord(header_group, callback)
    logger.debug(
        "canvas_chord_created",
        extra={
            "primitive": "chord",
            "application_id": application_id,
            "header_group_size": len(header),
            "callback_task": "aggregate_underwriting_decision",
            "note": "Assembled chord synchronization barrier across header group to callback",
        },
    )
    return workflow_chord


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
    logger.debug(
        "canvas_signature_s_created",
        extra={
            "primitive": ".s()",
            "application_id": application_id,
            "task": "validate_dossier",
            "role": "gatekeeper",
            "note": "Created mutable signature (.s()) for Stage 1 validation gatekeeper",
        },
    )
    logger.debug(
        "canvas_link_error_attached",
        extra={
            "primitive": "link_error",
            "application_id": application_id,
            "errback_task": "handle_workflow_failure",
            "note": "Attached on_error errback to validate_dossier signature",
        },
    )
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


def build_underwriting_chain(
    application_id: str,
    manifest: dict[str, str],
    applicant_name: str,
    requested_facility: Decimal | int | float | str,
) -> Any:
    """Construct a sequential workflow chain demonstrating .s() and .si() composition.

    Executes Stage 1 validation via mutable signature .s(), followed by
    an immutable audit notification signature .si() that completes the chain
    without being affected by the validation return value.

    Args:
        application_id: Credit application UUID string.
        manifest: Mapping of document types to file paths.
        applicant_name: Name of applicant.
        requested_facility: Amount requested.

    Returns:
        Celery chain signature ready for execution.
    """
    facility_dec = Decimal(str(requested_facility)) if not isinstance(requested_facility, Decimal) else requested_facility

    logger.debug(
        "canvas_signature_s_created",
        extra={
            "primitive": ".s()",
            "application_id": application_id,
            "task": "validate_dossier",
            "role": "chain_step_1",
            "note": "Created mutable signature (.s()) for initial validation step",
        },
    )
    step1 = validate_dossier.s(
        application_id, manifest, applicant_name, facility_dec
    )

    logger.debug(
        "canvas_signature_si_created",
        extra={
            "primitive": ".si()",
            "application_id": application_id,
            "task": "audit_notification_task",
            "role": "chain_step_2_immutable",
            "note": "Created immutable signature (.si()) for audit notification step in chain",
        },
    )
    step2 = audit_notification_task.si(application_id, "chain_validation_completed")

    workflow_chain = chain(step1, step2)
    logger.debug(
        "canvas_chain_created",
        extra={
            "primitive": "chain",
            "application_id": application_id,
            "steps": ["validate_dossier.s()", "audit_notification_task.si()"],
            "note": "Assembled sequential chain combining mutable .s() and immutable .si() signatures",
        },
    )
    return workflow_chain
