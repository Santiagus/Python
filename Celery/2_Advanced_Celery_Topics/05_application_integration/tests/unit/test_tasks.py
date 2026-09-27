"""Unit tests for Card Dispute Celery worker tasks and signal handlers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.logging_config import current_request_id
from services.worker.celery_app import (
    handle_task_postrun,
    handle_task_prerun,
    handle_worker_process_init,
)
from services.worker.tasks.disputes import _process_dispute_submission, submit_card_dispute_task
from services.worker.tasks.utils import (
    get_sync_executor,
    get_worker_loop,
    reset_worker_loop,
    run_sync,
    shutdown_sync_executor,
)


@pytest.mark.asyncio
async def test_process_dispute_submission_not_found() -> None:
    """Verify handling when the requested dispute ID does not exist."""
    dispute_id = str(uuid4())

    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.first.return_value = None
    mock_session.execute.return_value = mock_res

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    with patch("services.worker.tasks.disputes.get_session_factory", return_value=mock_factory):
        result = await _process_dispute_submission(dispute_id)

    assert result["status"] == "not_found"
    assert result["dispute_id"] == dispute_id


@pytest.mark.asyncio
async def test_process_dispute_submission_cooperative_cancellation() -> None:
    """Verify that worker cooperative check aborts cleanly when dispute status is cancelled."""
    dispute_id = str(uuid4())

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.status = "cancelled"
    mock_res = MagicMock()
    mock_res.first.return_value = mock_row
    mock_session.execute.return_value = mock_res

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    with patch("services.worker.tasks.disputes.get_session_factory", return_value=mock_factory):
        result = await _process_dispute_submission(dispute_id)

    assert result["status"] == "cancelled"
    assert "revoked in-flight" in result["message"]


@pytest.mark.asyncio
async def test_process_dispute_submission_already_terminal() -> None:
    """Verify that worker skips execution if dispute has already reached a terminal state."""
    dispute_id = str(uuid4())

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.status = "submitted_to_network"
    mock_res = MagicMock()
    mock_res.first.return_value = mock_row
    mock_session.execute.return_value = mock_res

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    with patch("services.worker.tasks.disputes.get_session_factory", return_value=mock_factory):
        result = await _process_dispute_submission(dispute_id)

    assert result["status"] == "submitted_to_network"
    assert "already in terminal state" in result["message"]


@pytest.mark.asyncio
async def test_process_dispute_submission_simulated_failure() -> None:
    """Verify simulated network failure transitions dispute to failed state."""
    dispute_id = str(uuid4())

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.status = "processing"
    select_res = MagicMock()
    select_res.first.return_value = mock_row

    mock_session.execute.side_effect = [select_res, MagicMock()]

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    with patch("services.worker.tasks.disputes.get_session_factory", return_value=mock_factory):
        result = await _process_dispute_submission(dispute_id, simulate_failure=True)

    assert result["status"] == "failed"
    assert "Clearinghouse timeout" in result["error"]
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_process_dispute_submission_happy_path() -> None:
    """Verify successful clearinghouse submission and atomic state update."""
    dispute_id = str(uuid4())

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.status = "processing"
    select_res = MagicMock()
    select_res.first.return_value = mock_row

    update_res = MagicMock()
    update_res.rowcount = 1

    mock_session.execute.side_effect = [select_res, update_res]

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    with patch("services.worker.tasks.disputes.get_session_factory", return_value=mock_factory):
        result = await _process_dispute_submission(dispute_id, simulate_failure=False)

    assert result["status"] == "submitted_to_network"
    assert result["dispute_id"] == dispute_id
    assert result["network_reference_id"].startswith("VROL-")
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_process_dispute_submission_superseded_by_cancellation() -> None:
    """Verify handling when cancellation commits in parallel right before worker update."""
    dispute_id = str(uuid4())

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.status = "processing"
    select_res = MagicMock()
    select_res.first.return_value = mock_row

    update_res = MagicMock()
    update_res.rowcount = 0  # Rowcount 0 indicates concurrent update changed the status

    mock_session.execute.side_effect = [select_res, update_res]

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    with patch("services.worker.tasks.disputes.get_session_factory", return_value=mock_factory):
        result = await _process_dispute_submission(dispute_id, simulate_failure=False)

    assert result["status"] == "cancelled"
    assert "concurrently" in result["message"]


def test_submit_card_dispute_task_wrapper() -> None:
    """Verify the Celery task wrapper executes and returns synchronously."""
    dispute_id = str(uuid4())
    expected = {"status": "submitted_to_network", "dispute_id": dispute_id}

    with patch(
        "services.worker.tasks.disputes._process_dispute_submission",
        new_callable=AsyncMock,
    ) as mock_process:
        mock_process.return_value = expected
        res = submit_card_dispute_task.run(dispute_id, simulate_failure=False)

    assert res == expected


def test_worker_signals() -> None:
    """Verify Celery prerun and postrun signal handlers bind and reset ContextVar."""
    task_mock = MagicMock()
    task_mock.name = "test_dispute_task"
    task_mock.request.headers = {"correlation_id": "test_corr_123"}

    # 1. Prerun sets ContextVar
    handle_task_prerun(sender=None, task_id="task_1", task=task_mock, args=(), kwargs={})
    assert current_request_id.get() == "test_corr_123"

    # 2. Postrun cleans up ContextVar
    handle_task_postrun(
        sender=None,
        task_id="task_1",
        task=task_mock,
        args=(),
        kwargs={},
        retval=None,
        state="SUCCESS",
    )
    assert current_request_id.get() is None

    # 3. Postrun with unknown task ID handles cleanly
    handle_task_postrun(
        sender=None,
        task_id="unknown_task",
        task=task_mock,
        args=(),
        kwargs={},
        retval=None,
        state="SUCCESS",
    )


def test_worker_process_init_signal() -> None:
    """Verify worker process init signal handler triggers DB warming."""
    with patch("services.worker.celery_app.init_worker_db") as mock_init:
        handle_worker_process_init()
        assert mock_init.called


def test_utils_event_loop_and_executor() -> None:
    """Verify worker event loop and executor utility functions."""
    # 1. Test worker loop lifecycle and clean reset
    loop = get_worker_loop()
    assert loop is not None
    assert not loop.is_closed()

    # Reset while open
    reset_worker_loop()

    # Reset when already None
    reset_worker_loop()

    # Reset when loop exists but is manually closed
    loop2 = get_worker_loop()
    loop2.close()
    reset_worker_loop()

    # 2. Test executor shutdown and re-initialization
    executor = get_sync_executor()
    assert executor is not None
    shutdown_sync_executor()
    # Calling shutdown again when already shut down
    shutdown_sync_executor()
    # Re-initialization when _shutdown is True
    executor_reinit = get_sync_executor()
    assert executor_reinit is not None
    assert not executor_reinit._shutdown

    # 3. Test run_sync outside of any active running event loop
    async def sample_coro() -> int:
        return 42

    res = run_sync(sample_coro())
    assert res == 42


@pytest.mark.asyncio
async def test_run_sync_inside_running_loop() -> None:
    """Verify run_sync safely bridges to the thread pool executor when called inside an active loop."""

    async def sample_coro(value: str) -> str:
        await asyncio.sleep(0.01)
        return f"processed_{value}"

    res = run_sync(sample_coro("test_val"))
    assert res == "processed_test_val"
