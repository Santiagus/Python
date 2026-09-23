"""Worker task execution utilities and synchronous event loop adapters.

Eagerly initializes persistent thread pools and event loop handlers at module load
to eliminate first-call warm time.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any, Coroutine, TypeVar
from typing import Any, Coroutine, TypeVar, cast

T = TypeVar("T")

_thread_local = threading.local()

# Shared process-level ThreadPoolExecutor initialized eagerly at module load
_sync_executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="sync_worker",
)


def get_sync_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return the eagerly initialized process-level ThreadPoolExecutor, re-initializing if needed.

    Returns:
        concurrent.futures.ThreadPoolExecutor: Reusable thread pool for sync-in-async bridging.
    """
    global _sync_executor
    if _sync_executor is None or _sync_executor._shutdown:
        _sync_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="sync_worker",
        )
    return _sync_executor


def shutdown_sync_executor() -> None:
    """Shut down the thread pool executor cleanly on process termination."""
    global _sync_executor
    if _sync_executor is not None and not _sync_executor._shutdown:
        _sync_executor.shutdown(wait=False, cancel_futures=True)


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent thread-local event loop, initializing it if needed.

    In Celery prefork, solo, or test worker processes, reusing a persistent event loop
    across task invocations preserves asyncpg connection pools and prevents 'Future attached
    to a different loop' errors caused by creating and destroying ephemeral loops.

    Returns:
        asyncio.AbstractEventLoop: Open, active event loop for the current thread.
    """
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _thread_local.loop = loop
    return loop


def reset_worker_loop() -> None:
    """Close and clear the current thread-local event loop."""
    loop = getattr(_thread_local, "loop", None)
    if loop is not None:
        if not loop.is_closed():
            loop.close()
        _thread_local.loop = None


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Execute an asynchronous coroutine synchronously, safe across running event loops.

    In standard Celery prefork or solo workers, executes on the worker thread's persistent
    event loop via loop.run_until_complete(coro). When invoked inside an already running
    event loop (such as pytest-asyncio tests), execution is safely delegated to the pooled
    background thread pool rather than spinning up and tearing down new executors.

    Args:
        coro: The async coroutine to execute.

    Returns:
        T: The return value of the coroutine.
    """
    # 1. Inspect whether the calling thread is already executing inside an active event loop
    try:
        asyncio.get_running_loop()
        is_running = True
    except RuntimeError:
        is_running = False

    # 2. When invoked inside an active loop (e.g. pytest-asyncio), reuse the shared thread pool
    if is_running:
        executor = get_sync_executor()
        return executor.submit(run_sync, coro).result()
        return cast(T, executor.submit(cast(Any, run_sync), coro).result())

    # 3. In synchronous worker processes, reuse the persistent thread-local loop
    loop = get_worker_loop()
    return loop.run_until_complete(coro)


