"""Tests for partial failure handling, Result Envelopes, and underwriter escalation policies."""

from uuid import uuid4
import pytest
from celery import chord

from services.worker.celery_app import celery_app
from services.worker.tasks import (
    validate_dossier,
    process_kyc_document,
    process_tax_return,
    process_bank_statement_page,
    aggregate_underwriting_decision,
)


@pytest.fixture(autouse=True)
def configure_eager_celery():
    """Ensure Celery runs in eager mode during partial failure tests."""
    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = orig_eager
    celery_app.conf.task_eager_propagates = orig_prop


class TestPartialFailureAndPolicies:
    """Test Result Envelope pattern and decision escalation paths."""

    def test_degraded_statement_page_escalation(self, degraded_dossier_manifest: dict[str, str]) -> None:
        """TC-02: Low OCR confidence on Page 2 returns degraded envelope, routing chord to manual_review."""
        app_id = str(uuid4())
        applicant_name = "JANE DOE"
        requested_facility = 200000.00

        # Stage 1: Validate and partition
        validation_result = validate_dossier.apply(
            args=[app_id, degraded_dossier_manifest, applicant_name, requested_facility]
        ).get()

        page_ids = validation_result["page_ids"]
        assert len(page_ids) == 3

        # Stage 2: Fan-out parallel chord
        header = [
            process_kyc_document.s(app_id, degraded_dossier_manifest["kyc_id"], applicant_name),
            process_tax_return.s(app_id, degraded_dossier_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, degraded_dossier_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]

        # Stage 3: Fan-in callback
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        # Invariant: Chord barrier did NOT crash; Result Envelope caught degraded page
        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "manual_review"
        assert any("degraded" in flag.lower() for flag in final_decision["audit_flags"])

    def test_kyc_identity_mismatch_fraud_escalation(self, clean_dossier_manifest: dict[str, str]) -> None:
        """TC-04: KYC ID name mismatch halts approval and issues a declined decision."""
        app_id = str(uuid4())
        fraudulent_applicant = "MARK DAVIS"  # Manifest name differs from ID name "JANE DOE"
        requested_facility = 150000.00

        # Stage 1: Validate and partition
        validation_result = validate_dossier.apply(
            args=[app_id, clean_dossier_manifest, fraudulent_applicant, requested_facility]
        ).get()

        page_ids = validation_result["page_ids"]

        # Stage 2: Fan-out parallel chord with mismatched applicant
        header = [
            process_kyc_document.s(app_id, clean_dossier_manifest["kyc_id"], fraudulent_applicant),
            process_tax_return.s(app_id, clean_dossier_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, clean_dossier_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]

        # Stage 3: Fan-in callback
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "declined"
        assert any("mismatch" in flag.lower() for flag in final_decision["audit_flags"])
        assert "Issues detected" in final_decision["summary"]

    def test_expired_kyc_escalation(self, expired_kyc_manifest: dict[str, str]) -> None:
        """Verify expired KYC document alone triggers declined decision with expired audit flag and summary."""
        app_id = str(uuid4())
        applicant_name = "JANE DOE"
        requested_facility = 250000.00

        validation_result = validate_dossier.apply(
            args=[app_id, expired_kyc_manifest, applicant_name, requested_facility]
        ).get()
        page_ids = validation_result["page_ids"]

        header = [
            process_kyc_document.s(app_id, expired_kyc_manifest["kyc_id"], applicant_name),
            process_tax_return.s(app_id, expired_kyc_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, expired_kyc_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "declined"
        assert any("expired" in flag.lower() for flag in final_decision["audit_flags"])
        assert "KYC document expired" in final_decision["summary"]

    def test_failed_tax_control_escalation(self, failed_tax_manifest: dict[str, str]) -> None:
        """Verify tax return failing DSCR control triggers declined decision with tax error in summary."""
        app_id = str(uuid4())
        applicant_name = "JANE DOE"
        requested_facility = 250000.00

        validation_result = validate_dossier.apply(
            args=[app_id, failed_tax_manifest, applicant_name, requested_facility]
        ).get()
        page_ids = validation_result["page_ids"]

        header = [
            process_kyc_document.s(app_id, failed_tax_manifest["kyc_id"], applicant_name),
            process_tax_return.s(app_id, failed_tax_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, failed_tax_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "declined"
        assert any("dscr baseline below minimum" in flag.lower() for flag in final_decision["audit_flags"])
        assert "Tax filing DSCR baseline below minimum" in final_decision["summary"]

    def test_insolvent_bank_statement_escalation(self, insolvent_statement_manifest: dict[str, str]) -> None:
        """Verify bank statement with expenses exceeding income triggers cashflow failure and decline."""
        app_id = str(uuid4())
        applicant_name = "JANE DOE"
        requested_facility = 250000.00

        validation_result = validate_dossier.apply(
            args=[app_id, insolvent_statement_manifest, applicant_name, requested_facility]
        ).get()
        page_ids = validation_result["page_ids"]

        header = [
            process_kyc_document.s(app_id, insolvent_statement_manifest["kyc_id"], applicant_name),
            process_tax_return.s(app_id, insolvent_statement_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, insolvent_statement_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "declined"
        assert any("cashflow failure" in flag.lower() for flag in final_decision["audit_flags"])
        assert "Bank statement cashflow failure" in final_decision["summary"]

    def test_multi_failure_expired_kyc_and_failed_tax_control(
        self, multi_failure_manifest: dict[str, str]
    ) -> None:
        """Verify multi-failure dossier reflects BOTH KYC expiration and tax control failure in summary."""
        app_id = str(uuid4())
        applicant_name = "JANE DOE"
        requested_facility = 250000.00

        validation_result = validate_dossier.apply(
            args=[app_id, multi_failure_manifest, applicant_name, requested_facility]
        ).get()
        page_ids = validation_result["page_ids"]

        header = [
            process_kyc_document.s(app_id, multi_failure_manifest["kyc_id"], applicant_name),
            process_tax_return.s(app_id, multi_failure_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, multi_failure_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "declined"
        # Verify BOTH errors are captured in audit flags
        assert any("expired" in flag.lower() for flag in final_decision["audit_flags"])
        assert any("dscr baseline below minimum" in flag.lower() for flag in final_decision["audit_flags"])
        # Verify summary reflects BOTH issues
        assert "KYC document expired" in final_decision["summary"]
        assert "Tax filing DSCR baseline below minimum" in final_decision["summary"]

    def test_triple_failure_all_processors_flagged(
        self, triple_failure_manifest: dict[str, str]
    ) -> None:
        """Verify triple failure reflects KYC, Tax, and Cashflow issues in summary and audit flags."""
        app_id = str(uuid4())
        applicant_name = "JANE DOE"
        requested_facility = 250000.00

        validation_result = validate_dossier.apply(
            args=[app_id, triple_failure_manifest, applicant_name, requested_facility]
        ).get()
        page_ids = validation_result["page_ids"]

        header = [
            process_kyc_document.s(app_id, triple_failure_manifest["kyc_id"], applicant_name),
            process_tax_return.s(app_id, triple_failure_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, triple_failure_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "declined"
        # All three processor errors must be reported
        assert any("expired" in flag.lower() for flag in final_decision["audit_flags"])
        assert any("dscr" in flag.lower() for flag in final_decision["audit_flags"])
        assert any("cashflow" in flag.lower() for flag in final_decision["audit_flags"])
        assert "KYC document expired" in final_decision["summary"]
        assert "Tax filing DSCR" in final_decision["summary"]
        assert "Bank statement cashflow" in final_decision["summary"]

