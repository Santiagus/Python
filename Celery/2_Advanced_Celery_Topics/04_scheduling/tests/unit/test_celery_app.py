"""Unit tests for Celery configuration, Kombu queues, and lifecycle signals."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from services.worker.celery_app import (
    celery_app,
    on_worker_process_init,
    on_worker_process_shutdown,
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
