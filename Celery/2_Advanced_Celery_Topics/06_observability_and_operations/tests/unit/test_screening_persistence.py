"""Unit tests for worker database persistence and execution utilities.

Tests _async_persist_screening, _async_persist_failure, and execution loop utilities.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.worker.tasks.screening import (
    _async_persist_failure,
    _async_persist_screening,
    _persist_failure,
    _persist_screening,
)
from services.worker.tasks.utils import (
    get_sync_executor,
    get_worker_loop,
    reset_worker_loop,
    run_sync,
    shutdown_sync_executor,
)


@pytest.mark.asyncio
async def test_async_persist_screening_success() -> None:
    """Verify _async_persist_screening executes update statement and records matches."""
    screening_id = str(uuid4())
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    matches = [
        {
            "entity_name": "Test Entity",
            "watchlist_type": "OFAC_SDN",
            "match_confidence": 99.5,
        }
    ]

    with patch("services.worker.tasks.screening.session_factory", mock_session_factory):
        await _async_persist_screening(
            screening_id=screening_id,
            status="blocked",
            risk_score=95,
            decision_reason="sanctions_watchlist_positive_match",
            matches=matches,
        )

    assert mock_session.execute.called
    assert mock_session.add.called
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_async_persist_screening_invalid_uuid() -> None:
    """Verify _async_persist_screening logs error on malformed UUID and returns early."""
    mock_session_factory = MagicMock()

    with patch("services.worker.tasks.screening.session_factory", mock_session_factory):
        await _async_persist_screening(
            screening_id="not-a-valid-uuid",
            status="approved",
            risk_score=10,
            decision_reason="clean",
        )

    assert not mock_session_factory.called


@pytest.mark.asyncio
async def test_async_persist_failure_success() -> None:
    """Verify _async_persist_failure updates status to failed with error message."""
    screening_id = str(uuid4())
    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    with patch("services.worker.tasks.screening.session_factory", mock_session_factory):
        await _async_persist_failure(
            screening_id=screening_id,
            error_msg="Connection timed out to sanctions api",
        )

    assert mock_session.execute.called
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_async_persist_failure_invalid_uuid() -> None:
    """Verify _async_persist_failure safely aborts on malformed UUID string."""
    mock_session_factory = MagicMock()

    with patch("services.worker.tasks.screening.session_factory", mock_session_factory):
        await _async_persist_failure(
            screening_id="invalid-uuid",
            error_msg="Some error",
        )

    assert not mock_session_factory.called


def test_persist_screening_sync_wrapper_catches_exception() -> None:
    """Verify _persist_screening handles and logs exceptions without crashing."""
    with patch(
        "services.worker.tasks.screening.run_sync",
        side_effect=RuntimeError("Database unreachable"),
    ):
        _persist_screening(
            screening_id=str(uuid4()),
            status="approved",
            risk_score=10,
            decision_reason="clean",
        )


def test_persist_failure_sync_wrapper_catches_exception() -> None:
    """Verify _persist_failure handles exceptions gracefully."""
    with patch(
        "services.worker.tasks.screening.run_sync",
        side_effect=RuntimeError("Database unreachable"),
    ):
        _persist_failure(
            screening_id=str(uuid4()),
            error_msg="fatal_crash",
        )


def test_worker_task_utils_lifecycle() -> None:
    """Verify get_sync_executor, shutdown_sync_executor, and loop utilities."""
    executor = get_sync_executor()
    assert executor is not None

    # Test re-initialization if shut down
    shutdown_sync_executor()
    reloaded_executor = get_sync_executor()
    assert reloaded_executor is not None
    assert not reloaded_executor._shutdown

    # Test event loop utilities
    loop = get_worker_loop()
    assert loop is not None
    reset_worker_loop()

    # Test run_sync in synchronous context
    async def sample_coro() -> int:
        await asyncio.sleep(0.01)
        return 42

    result = run_sync(sample_coro())
    assert result == 42


@pytest.mark.asyncio
async def test_run_sync_inside_running_event_loop() -> None:
    """Verify run_sync delegates to thread pool executor when called inside an active loop."""

    async def sample_coro() -> str:
        await asyncio.sleep(0.01)
        return "async_result"

    result = run_sync(sample_coro())
    assert result == "async_result"
