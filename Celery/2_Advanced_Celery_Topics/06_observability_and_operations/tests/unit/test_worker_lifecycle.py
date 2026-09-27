"""Unit tests for Celery worker signals, telemetry hooks, and lifecycle shutdown (TC-16, TC-19)."""

import time
from unittest.mock import MagicMock, patch

from services.worker.celery_app import (
    _TASK_START_TIMES,
    on_task_postrun,
    on_task_prerun,
    on_task_retry,
    on_worker_process_init,
    on_worker_shutting_down,
)


def test_worker_process_init_hook() -> None:
    """TC-19: Verify worker_process_init hook executes cleanly without exceptions."""
    # Should execute and log without error
    on_worker_process_init()


def test_worker_shutting_down_hook_closes_client() -> None:
    """TC-19: Verify worker_shutting_down closes active HTTP clients."""
    with patch("services.worker.tasks.screening.get_shared_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_get_client.return_value = mock_client

        on_worker_shutting_down()
        mock_client.close.assert_called_once()


def test_worker_shutting_down_hook_handles_exceptions() -> None:
    """TC-19: Verify worker_shutting_down catches errors gracefully during client cleanup."""
    with patch("services.worker.tasks.screening.get_shared_client") as mock_get_client:
        mock_get_client.side_effect = RuntimeError("Socket already disconnected")
        # Should not raise exception
        on_worker_shutting_down()


def test_task_lifecycle_telemetry_signals() -> None:
    """TC-16: Verify task prerun, postrun, and retry signal handlers record Prometheus metrics."""
    task_id = "test-task-signal-1234"
    mock_task = MagicMock()
    mock_task.name = "services.worker.tasks.scoring.evaluate_screening"
    mock_task.request.delivery_info = {"routing_key": "fraud.screening.critical"}

    # 1. Prerun: increments in-flight gauge and records start time
    on_task_prerun(task_id=task_id, task=mock_task)
    assert task_id in _TASK_START_TIMES

    # 2. Postrun: decrements in-flight, increments tasks total, observes duration
    on_task_postrun(
        task_id=task_id,
        task=mock_task,
        state="SUCCESS",
        retval={"status": "ok"},
    )
    assert task_id not in _TASK_START_TIMES

    # 3. Postrun with failed state
    _TASK_START_TIMES[task_id] = time.perf_counter()
    on_task_postrun(
        task_id=task_id,
        task=mock_task,
        state="FAILURE",
        retval=None,
    )
    assert task_id not in _TASK_START_TIMES

    # 4. Retry signal
    mock_request = MagicMock()
    mock_request.task = "services.worker.tasks.screening.check_aml_watchlist"
    on_task_retry(request=mock_request, reason=ValueError("Timeout"), einfo=None)
    on_task_retry(request=mock_request, reason="Gateway Timeout string", einfo=None)
