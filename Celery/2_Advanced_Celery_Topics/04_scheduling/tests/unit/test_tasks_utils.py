"""Unit tests for task execution utilities and sync-in-async bridging adapters."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.worker.tasks.utils import (
    get_sync_executor,
    get_worker_loop,
    reset_worker_loop,
    run_sync,
    shutdown_sync_executor,
)


@pytest.mark.unit
async def test_run_sync_inside_running_event_loop() -> None:
    """Verify run_sync safely bridges async code when invoked inside an active event loop."""

    async def sample_coro() -> int:
        await asyncio.sleep(0.01)
        return 42

    result = run_sync(sample_coro())
    assert result == 42


@pytest.mark.unit
def test_run_sync_outside_event_loop() -> None:
    """Verify run_sync executes properly in a synchronous thread without an active event loop."""

    async def sample_coro() -> str:
        return "sync_result"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_sync, sample_coro())
        assert future.result() == "sync_result"


@pytest.mark.unit
def test_sync_executor_lifecycle() -> None:
    """Verify get_sync_executor re-initialization and shutdown."""
    executor = get_sync_executor()
    assert executor is not None

    shutdown_sync_executor()
    # Re-acquisition must create a new executor if previous was shut down
    executor2 = get_sync_executor()
    assert executor2 is not None
    assert not executor2._shutdown


@pytest.mark.unit
def test_worker_loop_lifecycle() -> None:
    """Verify get_worker_loop reuse and reset_worker_loop cleanup."""
    loop1 = get_worker_loop()
    loop2 = get_worker_loop()
    assert loop1 is loop2

    reset_worker_loop()
    loop3 = get_worker_loop()
    assert loop3 is not None
    assert not loop3.is_closed()
    reset_worker_loop()
