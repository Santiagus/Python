"""Unit tests for Celery tasks, workflow dispatch, and worker persistence helpers."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.tasks import build_underwriting_chord, dispatch_underwriting_workflow
from app.tasks import (
    build_underwriting_chain,
    build_underwriting_chord,
    dispatch_underwriting_workflow,
)
from services.worker.tasks import (
    _get_db_connection_string,
    _persist_underwriting_memo,
    _persist_workflow_failure,
    _update_application_status,
    aggregate_underwriting_decision,
    audit_notification_task,
    handle_workflow_failure,
    process_bank_statement_page,
    process_kyc_document,
    process_tax_return,
    validate_dossier,
)


def test_validate_dossier_missing_bank_statement() -> None:
    """validate_dossier raises ValueError when bank_statement is missing from manifest."""
    app_id = str(uuid4())
    with pytest.raises(ValueError, match="Missing bank_statement in manifest"):
        validate_dossier(
            application_id=app_id,
            manifest={"kyc_id": "/path/to/id.jpg"},
            applicant_name="JANE DOE",
            requested_facility=100000.0,
        )


def test_dispatch_underwriting_workflow_validation_failure() -> None:
    """dispatch_underwriting_workflow returns failed validation result if validation fails."""
    app_id = str(uuid4())
    # Empty manifest will cause validate_dossier to fail
    res = dispatch_underwriting_workflow(
        application_id=app_id,
        manifest={},
        applicant_name="JANE DOE",
        requested_facility=100000.0,
    )
    assert res.failed()


def test_aggregate_underwriting_decision_empty_results_declined() -> None:
    """aggregate_underwriting_decision declines and computes zero metrics when page results are empty."""
    app_id = str(uuid4())
    decision = aggregate_underwriting_decision(
        page_results=[],
        application_id=app_id,
        requested_facility=250000.0,
    )
    assert decision["decision"] == "declined"
    assert decision["net_cashflow"] == 0.0
    assert decision["dscr"] == 0.0
    assert decision["net_cashflow"] == Decimal("0.00")
    assert decision["dscr"] == Decimal("0.0")
    assert decision["net_cashflow_cents"] == 0
    assert decision["total_revenue_cents"] == 0


def test_aggregate_underwriting_decision_legacy_fallback() -> None:
    """aggregate_underwriting_decision parses legacy Decimal/float keys without _cents."""
    app_id = str(uuid4())
    page_results = [
        {
            "status": "success",
            "document_type": "kyc_id",
            "data": {"full_name": "JANE DOE"},
        },
        {
            "status": "success",
            "document_type": "tax_filing",
            "data": {
                "dscr_baseline": Decimal("2.50"),
                "gross_receipts": Decimal("500000.00"),
            },
        },
        {
            "status": "success",
            "page_number": 1,
            "starting_balance": Decimal("50000.00"),
        },
        {
            "status": "success",
            "page_number": 2,
            "total_deposits": Decimal("30000.00"),
            "total_withdrawals": Decimal("10000.00"),
        },
    ]
    decision = aggregate_underwriting_decision(
        page_results=page_results,
        application_id=app_id,
        requested_facility=Decimal("100000.00"),
    )
    assert decision["decision"] == "approved"
    assert decision["net_cashflow_cents"] == 2000000
    assert decision["total_revenue_cents"] == 50000000
    assert decision["net_cashflow"] == Decimal("20000.00")
    assert decision["total_revenue"] == Decimal("500000.00")


def test_persist_underwriting_memo_and_workflow_failure_with_mock_db() -> None:
    """Verify _persist_underwriting_memo, _persist_workflow_failure, and _update_application_status execute commit."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("psycopg.connect", return_value=mock_conn):
        mock_conn.__enter__.return_value = mock_conn
        _persist_underwriting_memo(
            application_id=str(uuid4()),
            decision="approved",
            dscr=1.85,
            net_cashflow=30000.0,
            total_revenue=1000000.0,
            audit_flags=["TEST_FLAG"],
            stage_timings={"total_pipeline_ms": 200.0},
            summary="Test summary",
        )
        mock_conn.commit.assert_called_once()

    mock_conn_fail = MagicMock()
    mock_cur_fail = MagicMock()
    mock_conn_fail.cursor.return_value.__enter__.return_value = mock_cur_fail
    with patch("psycopg.connect", return_value=mock_conn_fail):
        mock_conn_fail.__enter__.return_value = mock_conn_fail
        _persist_workflow_failure(
            application_id=str(uuid4()),
            error_message="Test failure reason",
        )
        mock_conn_fail.commit.assert_called_once()

    mock_conn_status = MagicMock()
    mock_cur_status = MagicMock()
    mock_conn_status.cursor.return_value.__enter__.return_value = mock_cur_status
    with patch("psycopg.connect", return_value=mock_conn_status):
        mock_conn_status.__enter__.return_value = mock_conn_status
        _update_application_status(
            application_id=str(uuid4()),
            status="validating",
        )
        mock_conn_status.commit.assert_called_once()


def test_persist_functions_handle_exceptions_gracefully() -> None:
    """Verify persistence helpers catch DB connection and execution errors without raising."""
    with patch("psycopg.connect", side_effect=Exception("Database connection failed")):
        # Should not raise exception
        _persist_underwriting_memo(
            application_id=str(uuid4()),
            decision="declined",
            dscr=0.5,
            net_cashflow=-10000.0,
            total_revenue=500000.0,
            audit_flags=["FAIL"],
            stage_timings={},
            summary="Failure memo",
        )

        _persist_workflow_failure(
            application_id="invalid-uuid",
            error_message="Failure error",
        )

        _update_application_status(
            application_id="invalid-uuid",
            status="validating",
        )


def test_audit_notification_and_error_handling_tasks() -> None:
    """Verify audit notification task and error handler task execute properly."""
    app_id = str(uuid4())
    audit_res = audit_notification_task(app_id, "dossier_submitted")
    assert audit_res["status"] == "delivered"
    assert audit_res["application_id"] == app_id
    assert audit_res["event"] == "dossier_submitted"

    # Handle workflow failure task
    handle_workflow_failure(
        request=MagicMock(),
        exc=ValueError("Test error"),
        traceback=None,
        application_id=app_id,
    )


def test_build_underwriting_chain(clean_dossier_manifest: dict[str, str]) -> None:
    """Verify build_underwriting_chain constructs sequential chain with .s() and .si()."""
    app_id = str(uuid4())
    workflow_chain = build_underwriting_chain(
        application_id=app_id,
        manifest=clean_dossier_manifest,
        applicant_name="JANE DOE",
        requested_facility=250000.00,
    )
    assert workflow_chain is not None
    # Verify chain execution in eager mode
    res = workflow_chain.apply()
    assert res.successful()
    result = res.get()
    assert result["status"] == "delivered"
    assert result["application_id"] == app_id
    assert result["event"] == "chain_validation_completed"
