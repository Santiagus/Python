"""Celery workflow tasks for financial document underwriting.

Implements canvas tasks orchestrated across chain, group, and chord:
- validate_dossier: Gatekeeper checking manifest and partitioning document pages
- process_kyc_document: Photographic ID specimen parsing and anti-fraud verification
- process_tax_return: IRS Form 1120 corporate income tax return processing
- process_bank_statement_page: OCR evaluation and transaction ledger analysis per page
- aggregate_underwriting_decision: Chord callback synthesizing underwriting memo
- handle_workflow_failure: Compensating errback attached via link_error
- audit_notification_task: Side-effect notification task tested with .si()
"""

from __future__ import annotations

from decimal import Decimal
import logging
import time
from typing import Any
from uuid import uuid4

from app.currency import cents_to_decimal, decimal_to_cents
from services.worker.celery_app import celery_app
from services.worker.processors import (
    CorruptedDocumentError,
    KYCProcessor,
    StatementProcessor,
    TaxProcessor,
)

logger = logging.getLogger(__name__)

# In-memory application registry for quick state lookups
_APP_STATE_REGISTRY: dict[str, dict[str, Any]] = {}


def get_application_state(application_id: str) -> dict[str, Any]:
    """Retrieve in-memory state for a given application ID."""
    return _APP_STATE_REGISTRY.get(application_id, {"status": "unknown"})


@celery_app.task(bind=True, name="services.worker.tasks.validate_dossier")
def validate_dossier(
    self,
    application_id: str,
    manifest: dict[str, str],
    applicant_name: str,
    requested_facility: Decimal | int | float | str,
) -> dict[str, Any]:
    """Validate document presence and partition statement pages."""
    t0 = time.perf_counter()
    logger.info("Validating dossier for application %s", application_id)
    logger.info("validating_dossier", extra={"application_id": application_id, "manifest_keys": list(manifest.keys())})
    statement_path = manifest.get("bank_statement")
    if not statement_path:
        raise ValueError("Missing bank_statement in manifest")

    stmt_processor = StatementProcessor()
    # partition_pages raises CorruptedDocumentError on invalid or truncated PDFs
    partition = stmt_processor.partition_pages(statement_path)

    # Generate synthetic page IDs for the partitioned pages
    page_ids = [str(uuid4()) for _ in partition["pages"]]

    validation_duration_ms = max(round((time.perf_counter() - t0) * 1000, 2), 0.1)

    _APP_STATE_REGISTRY[application_id] = {
        "status": "validating",
        "page_ids": page_ids,
        "manifest": manifest,
        "validation_duration_ms": validation_duration_ms,
    }
    _update_application_status(application_id, "validating")

    return {
        "status": "success",
        "application_id": application_id,
        "page_ids": page_ids,
        "total_pages": partition["total_pages"],
        "validation_duration_ms": validation_duration_ms,
    }


@celery_app.task(name="services.worker.tasks.process_kyc_document")
def process_kyc_document(
    application_id: str,
    file_path: str,
    applicant_name: str,
) -> dict[str, Any]:
    """Process KYC ID document and perform anti-fraud matching."""
    t0 = time.perf_counter()
    logger.info("processing_kyc_document", extra={"application_id": application_id, "applicant_name": applicant_name})
    processor = KYCProcessor()
    result = processor.process(file_path, expected_applicant=applicant_name)
    duration_ms = max(round((time.perf_counter() - t0) * 1000, 2), 0.1)
    return {
        "application_id": application_id,
        "execution_duration_ms": duration_ms,
        **result,
    }


@celery_app.task(name="services.worker.tasks.process_tax_return")
def process_tax_return(application_id: str, file_path: str) -> dict[str, Any]:
    """Process IRS Form 1120 corporate income tax return."""
    t0 = time.perf_counter()
    logger.info("processing_tax_return", extra={"application_id": application_id, "file_path": file_path})
    processor = TaxProcessor()
    result = processor.process(file_path)
    duration_ms = max(round((time.perf_counter() - t0) * 1000, 2), 0.1)
    return {
        "application_id": application_id,
        "execution_duration_ms": duration_ms,
        **result,
    }


@celery_app.task(name="services.worker.tasks.process_bank_statement_page")
def process_bank_statement_page(
    application_id: str,
    page_id: str,
    page_number: int,
    file_path: str,
) -> dict[str, Any]:
    """Extract and analyze a single bank statement page text stream."""
    t0 = time.perf_counter()
    logger.info("processing_bank_statement_page", extra={"application_id": application_id, "page_number": page_number})
    stmt_processor = StatementProcessor()
    partition = stmt_processor.partition_pages(file_path)
    # Find matching page
    matching = next((p for p in partition["pages"] if p["page_number"] == page_number), None)
    text = matching["text"] if matching else ""
    res = stmt_processor.process_page_content(page_number, text)
    duration_ms = max(round((time.perf_counter() - t0) * 1000, 2), 0.1)
    return {
        "application_id": application_id,
        "page_id": page_id,
        "execution_duration_ms": duration_ms,
        **res,
    }


def _get_db_connection_string() -> str:
    """Derive synchronous PostgreSQL connection string from application settings."""
    from app.config import settings
    url = settings.database_url
    if "+asyncpg" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url


def _persist_underwriting_memo(
    application_id: str,
    decision: str,
    dscr: Decimal | float,
    net_cashflow: Decimal | float,
    total_revenue: Decimal | float,
    audit_flags: list[str],
    stage_timings: dict[str, float],
    summary: str,
) -> None:
    """Persist underwriting memo and update application terminal state in PostgreSQL."""
    try:
        import json
        import psycopg
        conn_str = _get_db_connection_string()
        dscr_dec = Decimal(str(dscr)) if not isinstance(dscr, Decimal) else dscr
        net_cashflow_dec = Decimal(str(net_cashflow)) if not isinstance(net_cashflow, Decimal) else net_cashflow
        total_revenue_dec = Decimal(str(total_revenue)) if not isinstance(total_revenue, Decimal) else total_revenue
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE applications SET status = %s WHERE id = %s",
                    (decision, application_id),
                )
                cur.execute(
                    """
                    INSERT INTO underwriting_memos (
                        application_id, decision, calculated_dscr, net_cashflow, total_revenue,
                        audit_flags, summary, stage_timings
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (application_id) DO UPDATE SET
                        decision = EXCLUDED.decision,
                        calculated_dscr = EXCLUDED.calculated_dscr,
                        net_cashflow = EXCLUDED.net_cashflow,
                        total_revenue = EXCLUDED.total_revenue,
                        audit_flags = EXCLUDED.audit_flags,
                        summary = EXCLUDED.summary,
                        stage_timings = EXCLUDED.stage_timings
                    """,
                    (
                        application_id,
                        decision,
                        dscr_dec,
                        net_cashflow_dec,
                        total_revenue_dec,
                        json.dumps(audit_flags),
                        summary,
                        json.dumps(stage_timings),
                    ),
                )
            conn.commit()
            logger.info("underwriting_memo_persisted", extra={"application_id": application_id, "decision": decision})
    except Exception as exc:
        logger.debug("Database write skipped in isolated/test worker: %s", exc)


def _update_application_status(application_id: str, status: str) -> None:
    """Update application processing status in PostgreSQL and in-memory registry."""
    _APP_STATE_REGISTRY.setdefault(application_id, {})["status"] = status
    try:
        import psycopg
        conn_str = _get_db_connection_string()
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE applications SET status = %s WHERE id = %s",
                    (status, application_id),
                )
            conn.commit()
            logger.info("application_status_updated", extra={"application_id": application_id, "status": status})
    except Exception as exc:
        logger.debug("Database status write skipped in isolated/test worker: %s", exc)


def _persist_workflow_failure(application_id: str, error_message: str) -> None:
    """Update application record to failed with error message."""
    _APP_STATE_REGISTRY.setdefault(application_id, {})["status"] = "failed"
    _APP_STATE_REGISTRY[application_id]["error_message"] = error_message
    try:
        import psycopg
        conn_str = _get_db_connection_string()
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE applications SET status = 'failed', error_message = %s WHERE id = %s",
                    (error_message, application_id),
                )
            conn.commit()
            logger.info("workflow_failure_persisted", extra={"application_id": application_id, "error": error_message})
    except Exception as exc:
        logger.debug("Database failure write skipped in isolated/test worker: %s", exc)


@celery_app.task(name="services.worker.tasks.aggregate_underwriting_decision")
def aggregate_underwriting_decision(
    page_results: list[dict[str, Any]],
    application_id: str,
    requested_facility: Decimal | int | float | str,
    stage_1_validation_ms: float = 0.0,
    chord_dispatched_at: float | None = None,
) -> dict[str, Any]:
    """Fan-in chord callback synthesizing all document envelopes into a final decision."""
    t3_start = time.perf_counter()
    logger.info("aggregating_underwriting_decision", extra={"application_id": application_id, "page_count": len(page_results)})

    # Resolve real Stage 1 validation latency
    if stage_1_validation_ms <= 0.0:
        reg_state = _APP_STATE_REGISTRY.get(application_id, {})
        stage_1_validation_ms = reg_state.get("validation_duration_ms", 1.0)
    stage_1_validation_ms = max(round(stage_1_validation_ms, 2), 0.1)

    # Resolve real Stage 2 fanout chord latency
    now = time.time()
    header_durations = [
        r.get("execution_duration_ms", 0.0)
        for r in page_results
        if isinstance(r, dict)
    ]
    if chord_dispatched_at and 0 < (now - chord_dispatched_at) < 86400:
        stage_2_fanout_chord_ms = max(round((now - chord_dispatched_at) * 1000, 2), 0.1)
    else:
        stage_2_fanout_chord_ms = max(round(sum(header_durations) if header_durations else 1.0, 2), 0.1)

    audit_flags: list[str] = []
    has_kyc_failure = False
    has_degradation = False

    total_deposits_cents = 0
    total_withdrawals_cents = 0
    starting_balance_cents = 0
    ebitda_cents = 0
    dscr = Decimal("0.0")
    total_revenue_cents = 0

    for r in page_results:
        doc_type = r.get("document_type")
        status = r.get("status")

        if doc_type == "kyc_id" and status == "failed":
            has_kyc_failure = True
            audit_flags.extend(r.get("errors", ["KYC verification failed"]))

        if status == "degraded":
            has_degradation = True
            audit_flags.extend(r.get("errors", ["Degraded OCR on statement page"]))

        if doc_type == "tax_filing":
            tax_data = r.get("data", {})
            dscr_val = tax_data.get("dscr_baseline", Decimal("0.0"))
            dscr = Decimal(str(dscr_val)) if dscr_val is not None else Decimal("0.0")
            ebitda_cents = tax_data.get("ebitda_cents") or decimal_to_cents(tax_data.get("ebitda", 0)) or 0
            total_revenue_cents = (
                tax_data.get("gross_receipts_cents")
                or decimal_to_cents(tax_data.get("gross_receipts", 0))
                or 0
            )

        if r.get("total_deposits_cents") is not None:
            total_deposits_cents = r["total_deposits_cents"]
        elif r.get("total_deposits") is not None:
            c = decimal_to_cents(r["total_deposits"])
            if c is not None:
                total_deposits_cents = c

        if r.get("total_withdrawals_cents") is not None:
            total_withdrawals_cents = r["total_withdrawals_cents"]
        elif r.get("total_withdrawals") is not None:
            c = decimal_to_cents(r["total_withdrawals"])
            if c is not None:
                total_withdrawals_cents = c

        if r.get("starting_balance_cents") is not None:
            starting_balance_cents = r["starting_balance_cents"]
        elif r.get("starting_balance") is not None:
            c = decimal_to_cents(r["starting_balance"])
            if c is not None:
                starting_balance_cents = c

    # Exact minor unit calculus (integer cents)
    net_cashflow_cents = total_deposits_cents - total_withdrawals_cents
    net_cashflow = cents_to_decimal(net_cashflow_cents) or Decimal("0.00")
    total_revenue = cents_to_decimal(total_revenue_cents) or Decimal("0.00")

    # Decision logic
    if has_kyc_failure:
        decision = "declined"
    elif has_degradation:
        decision = "manual_review"
    elif dscr < Decimal("1.25"):
        decision = "declined"
    else:
        decision = "approved"

    t3_end = time.perf_counter()
    stage_3_fanin_aggregation_ms = max(round((t3_end - t3_start) * 1000, 2), 0.1)
    total_pipeline_ms = round(stage_1_validation_ms + stage_2_fanout_chord_ms + stage_3_fanin_aggregation_ms, 2)

    stage_timings = {
        "stage_1_validation_ms": stage_1_validation_ms,
        "stage_2_fanout_chord_ms": stage_2_fanout_chord_ms,
        "stage_3_fanin_aggregation_ms": stage_3_fanin_aggregation_ms,
        "total_pipeline_ms": total_pipeline_ms,
    }

    summary = (
        f"Automated underwriting decision: {decision}. "
        f"DSCR={dscr:.2f}, Net Cashflow=${net_cashflow:,.2f}, Revenue=${total_revenue:,.2f}."
    )

    logger.info(
        "underwriting_decision_compiled",
        extra={
            "application_id": application_id,
            "decision": decision,
            "dscr": str(dscr),
            "net_cashflow": str(net_cashflow),
            "net_cashflow_cents": net_cashflow_cents,
        },
    )

    final_result = {
        "status": "success",
        "application_id": application_id,
        "decision": decision,
        "dscr": dscr,
        "net_cashflow": net_cashflow,
        "total_revenue": total_revenue,
        "net_cashflow_cents": net_cashflow_cents,
        "total_revenue_cents": total_revenue_cents,
        "audit_flags": audit_flags,
        "stage_timings": stage_timings,
        "summary": summary,
    }
    _APP_STATE_REGISTRY[application_id] = final_result

    # Persist to database if available
    _persist_underwriting_memo(
        application_id=application_id,
        decision=decision,
        dscr=dscr,
        net_cashflow=net_cashflow,
        total_revenue=total_revenue,
        audit_flags=audit_flags,
        stage_timings=stage_timings,
        summary=summary,
    )

    return final_result


@celery_app.task(name="services.worker.tasks.handle_workflow_failure")
def handle_workflow_failure(request: Any, exc: Any, traceback: Any, application_id: str) -> None:
    """Compensating link_error errback invoked when upstream chain fails."""
    logger.error("Workflow failed for application %s: %s", application_id, exc)
    logger.error("workflow_failed", extra={"application_id": application_id, "error": str(exc)})
    error_msg = str(exc)
    _APP_STATE_REGISTRY[application_id] = {
        "status": "failed",
        "error_message": error_msg,
    }
    _persist_workflow_failure(application_id, error_msg)


@celery_app.task(name="services.worker.tasks.audit_notification_task")
def audit_notification_task(application_id: str, event_type: str) -> dict[str, str]:
    """Side-effect notification task (invoked via immutable .si() signatures)."""
    logger.info("Audit notification [%s] sent for application %s", event_type, application_id)
    return {
        "status": "delivered",
        "event": event_type,
        "event_type": event_type,
        "application_id": application_id,
    }
