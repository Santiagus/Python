"""Unit tests for Celery configuration, Kombu queues, and lifecycle signals."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.logging_config import current_request_id
from services.worker.celery_app import (
    celery_app,
    handle_task_postrun,
    handle_task_prerun,
    on_worker_process_init,
    on_worker_process_shutdown,
    setup_celery_logger,
    setup_celery_task_logger,
)


@pytest.mark.unit
def test_celery_configuration() -> None:
    """Verify Celery application serializer, timezone, and queue routing configurations."""
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.timezone == "America/New_York"
    assert conf.enable_utc is True
    assert conf.task_default_queue == "reconciliation"

    queue_names = [q.name for q in conf.task_queues]
    assert "reconciliation" in queue_names
    assert "cleanup" in queue_names


@pytest.mark.unit
def test_worker_process_init_signal() -> None:
    """Verify worker_process_init signal hook warms the database pool."""
    on_worker_process_init()


@pytest.mark.unit
async def test_worker_process_shutdown_signal_running_loop() -> None:
    """Verify worker_process_shutdown signal hook disposes pools when event loop is running."""
    on_worker_process_shutdown()


@pytest.mark.unit
def test_worker_process_shutdown_signal_stopped_loop() -> None:
    """Verify worker_process_shutdown signal hook works when loop is not currently active."""
    new_loop = asyncio.new_event_loop()
    with patch("asyncio.get_event_loop", return_value=new_loop):
        on_worker_process_shutdown()
    new_loop.close()


@pytest.mark.unit
def test_worker_process_shutdown_signal_exception() -> None:
    """Verify worker_process_shutdown catches exceptions gracefully and closes Redis."""
    with patch("asyncio.get_event_loop", side_effect=RuntimeError("Loop error")):
        on_worker_process_shutdown()


@pytest.mark.unit
def test_celery_logger_setup_signals() -> None:
    """Verify Celery logger setup hooks attach PrettyDevFormatter and filter."""
    test_logger = logging.getLogger("celery.test_worker")
    test_logger.handlers.clear()
    handler = logging.StreamHandler()
    test_logger.addHandler(handler)

    setup_celery_logger(test_logger)
    assert len(handler.filters) >= 1

    task_logger = logging.getLogger("celery.test_task")
    task_logger.handlers.clear()
    task_handler = logging.StreamHandler()
    task_logger.addHandler(task_handler)

    setup_celery_task_logger(task_logger)
    assert len(task_handler.filters) >= 1


@pytest.mark.unit
def test_task_prerun_and_postrun_signals() -> None:
    """Verify task prerun extracts correlation ID and postrun cleans up token."""
    mock_task = MagicMock()
    mock_task.name = "test_task"
    mock_task.request.headers = {"correlation_id": "corr_uuid_12345678"}

    task_id = "task_uuid_abc123"

    # 1. Prerun binds correlation ID to ContextVar
    handle_task_prerun(sender=None, task_id=task_id, task=mock_task, args=(), kwargs={})
    assert current_request_id.get() == "corr_uuid_12345678"

    # 2. Postrun cleans up token
    handle_task_postrun(
        sender=None,
        task_id=task_id,
        task=mock_task,
        args=(),
        kwargs={},
        retval=None,
        state="SUCCESS",
    )
    assert current_request_id.get() is None
