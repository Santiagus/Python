"""Tests for Celery Canvas workflow primitives (chain, group, chord, link_error, .s() vs .si()).

These tests execute the workflow graphs using Celery's eager mode with in-memory backend
to assert graph structure, execution ordering, barrier synchronization, and error propagation.
"""

from uuid import uuid4
import pytest
from celery import chain, chord, group

from services.worker.celery_app import celery_app
from services.worker.tasks import (
    validate_dossier,
    process_kyc_document,
    process_tax_return,
    process_bank_statement_page,
    aggregate_underwriting_decision,
    handle_workflow_failure,
    audit_notification_task,
)


@pytest.fixture(autouse=True)
def configure_eager_celery():
    """Ensure Celery runs in eager mode during canvas tests."""
    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = orig_eager
    celery_app.conf.task_eager_propagates = orig_prop


class TestCanvasWorkflows:
    """Test Celery Canvas coordination and signatures."""

    def test_happy_path_workflow(self, clean_dossier_manifest: dict[str, str]) -> None:
        """TC-01: Full underwriting workflow passes clean manifest to chain -> chord -> callback."""
        app_id = str(uuid4())
        applicant_name = "JANE DOE"
        requested_facility = 250000.00

        # Stage 1: Validate dossier and partition pages
        validation_result = validate_dossier.apply(
            args=[app_id, clean_dossier_manifest, applicant_name, requested_facility]
        ).get()

        assert validation_result["status"] == "success"
        page_ids = validation_result["page_ids"]
        assert len(page_ids) == 4

        # Stage 2: Fan-out parallel chord header
        header = [
            process_kyc_document.s(app_id, clean_dossier_manifest["kyc_id"], applicant_name),
            process_tax_return.s(app_id, clean_dossier_manifest["tax_filing"]),
            *[
                process_bank_statement_page.s(app_id, pid, pnum, clean_dossier_manifest["bank_statement"])
                for pnum, pid in enumerate(page_ids, start=1)
            ],
        ]

        # Stage 3: Fan-in aggregation callback
        workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
        final_decision = workflow.get()

        assert final_decision["status"] == "success"
        assert final_decision["decision"] == "approved"
        assert final_decision["dscr"] >= 1.25
        assert final_decision["audit_flags"] == []

    def test_corrupted_dossier_link_error(self, corrupted_dossier_manifest: dict[str, str]) -> None:
        """TC-03: Corrupted document triggers fast-fail in Stage 1 and routes to link_error errback."""
        app_id = str(uuid4())

        # Build task with link_error attached
        task_sig = validate_dossier.s(
            app_id, corrupted_dossier_manifest, "JANE DOE", 100000.00
        ).on_error(handle_workflow_failure.s(app_id))

        res = task_sig.apply()
        # In eager mode with link_error, task status reflects failure
        assert res.failed()

        # Verify compensating callback set application to failed
        from services.worker.tasks import get_application_state
        state = get_application_state(app_id)
        assert state["status"] == "failed"
        assert "corrupt" in state.get("error_message", "").lower()

    def test_signature_discipline_s_vs_si(self) -> None:
        """TC-05: Verify mutable signature .s() injects upstream args, while immutable .si() isolates side effects."""
        app_id = str(uuid4())

        # Mutable .s() should receive upstream return values
        @celery_app.task
        def step_one():
            return {"metric": 42}

        @celery_app.task
        def step_two_mutable(upstream_result):
            assert upstream_result == {"metric": 42}
            return upstream_result["metric"] * 2

        res_mutable = chain(step_one.s(), step_two_mutable.s()).apply().get()
        assert res_mutable == 84

        # Immutable .si() does NOT receive upstream return values, avoiding TypeError
        res_immutable = chain(
            step_one.s(),
            audit_notification_task.si(app_id, "AUDIT_EVENT_TRIGGERED"),
        ).apply().get()

        assert res_immutable["event"] == "AUDIT_EVENT_TRIGGERED"
        assert res_immutable["application_id"] == app_id

