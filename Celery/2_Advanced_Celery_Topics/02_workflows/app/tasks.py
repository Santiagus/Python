"""Celery client workflow builder and dispatcher for credit underwriting.

Constructs and dispatches the multi-stage Celery Canvas graph:
1. Sequential Gatekeeper (validate_dossier) with link_error errback
2. Parallel Chord Header (process_kyc_document, process_tax_return, process_bank_statement_page)
3. Fan-in Synthesis Callback (aggregate_underwriting_decision)
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from celery import chord
from celery.result import AsyncResult

from services.worker.celery_app import celery_app
from services.worker.tasks import (
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
    requested_facility: float,
    page_ids: list[str],
) -> Any:
    """Construct the parallel chord canvas stage for an underwriting dossier.

    Args:
        application_id: Credit application UUID string.
        manifest: Mapping of document types to storage file paths.
        applicant_name: Legal applicant name from application manifest.
        requested_facility: Dollar facility amount requested.
        page_ids: List of partitioned bank statement page UUID strings.

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

    callback = aggregate_underwriting_decision.s(application_id, requested_facility)
    return chord(header, callback)


def dispatch_underwriting_workflow(
    application_id: str,
    manifest: dict[str, str],
    applicant_name: str,
    requested_facility: float,
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

    # Stage 1: Validate dossier with link_error errback attached
    validation_sig = validate_dossier.s(
        application_id, manifest, applicant_name, requested_facility
    ).on_error(handle_workflow_failure.s(application_id))

    validation_res = validation_sig.apply()
    if validation_res.failed():
        logger.warning("Dossier validation failed for %s", application_id)
        return validation_res

    validation_result = validation_res.get()
    page_ids = validation_result.get("page_ids", [])

    # Stages 2 & 3: Parallel chord fan-out and fan-in aggregation
    workflow_chord = build_underwriting_chord(
        application_id=application_id,
        manifest=manifest,
        applicant_name=applicant_name,
        requested_facility=requested_facility,
        page_ids=page_ids,
    )

    return workflow_chord.apply_async()
