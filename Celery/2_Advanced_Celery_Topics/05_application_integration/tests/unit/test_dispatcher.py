"""Unit tests for AMQP task dispatcher and revocation broadcaster."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.dispatcher import (
    DISPUTE_TASK_NAME,
    dispatch_dispute_submission,
    revoke_dispute_task,
)
from app.logging_config import current_request_id


def test_dispatch_dispute_submission_with_context() -> None:
    """Verify dispatch_dispute_submission binds existing correlation context to headers."""
    dispute_id = str(uuid4())
    req_id = "test-corr-id-999"
    token = current_request_id.set(req_id)

    mock_result = MagicMock()
    mock_result.id = "celery-task-uuid-111"

    try:
        with patch("app.dispatcher.submit_card_dispute_task.apply_async", return_value=mock_result) as mock_apply:
            task_id = dispatch_dispute_submission(dispute_id=dispute_id, simulate_failure=True)
            assert task_id == "celery-task-uuid-111"

            mock_apply.assert_called_once_with(
                args=[dispute_id, True],
                headers={
                    "correlation_id": req_id,
                    "request_id": req_id,
                    "source": "api_gateway",
                },
            )
    finally:
        current_request_id.reset(token)


def test_dispatch_dispute_submission_fallback_context() -> None:
    """Verify dispatch_dispute_submission generates a new correlation UUID when ContextVar is None."""
    dispute_id = str(uuid4())
    current_request_id.set(None)

    mock_result = MagicMock()
    mock_result.id = "celery-task-uuid-222"

    with patch("app.dispatcher.submit_card_dispute_task.apply_async", return_value=mock_result) as mock_apply:
        task_id = dispatch_dispute_submission(dispute_id=dispute_id, simulate_failure=False)
        assert task_id == "celery-task-uuid-222"

        call_kwargs = mock_apply.call_args.kwargs
        headers = call_kwargs["headers"]
        assert headers["correlation_id"] is not None
        assert headers["source"] == "api_gateway"


def test_revoke_dispute_task() -> None:
    """Verify revoke_dispute_task broadcasts SIGTERM control revoke."""
    with patch("app.dispatcher.celery_app.control.revoke") as mock_revoke:
        revoke_dispute_task("task-to-cancel-123")
        mock_revoke.assert_called_once_with(
            "task-to-cancel-123",
            terminate=True,
            signal="SIGTERM",
        )

        # Empty string handling (no-op)
        mock_revoke.reset_mock()
        revoke_dispute_task("")
        assert not mock_revoke.called


def test_dispute_task_name_constant() -> None:
    """Verify task name constant matches expected task path."""
    assert DISPUTE_TASK_NAME == "services.worker.tasks.disputes.submit_card_dispute_task"
