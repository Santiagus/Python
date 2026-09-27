"""Asynchronous AMQP task dispatcher for card dispute lifecycle tasks.

The API gateway never executes Celery tasks directly; it prepares payloads,
injects correlation tracing headers, and publishes AMQP messages via this dispatcher.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.logging_config import current_request_id
from services.worker.celery_app import celery_app
from services.worker.tasks.disputes import submit_card_dispute_task

logger = logging.getLogger(__name__)

# Task name constant enforced by contract testing
DISPUTE_TASK_NAME = "services.worker.tasks.disputes.submit_card_dispute_task"


def dispatch_dispute_submission(
    dispute_id: str,
    simulate_failure: bool = False,
) -> str:
    """Publish a dispute submission task message to RabbitMQ with tracing context.

    Args:
        dispute_id: String UUID of the persisted card dispute.
        simulate_failure: Diagnostic flag to simulate clearinghouse network timeout.

    Returns:
        str: Celery task ID for tracking or remote revocation.
    """
    # 1. Resolve correlation context for end-to-end tracing across distributed processes
    req_id = current_request_id.get() or str(uuid4())
    headers = {
        "correlation_id": req_id,
        "request_id": req_id,
        "source": "api_gateway",
    }

    # 2. Publish Celery canvas signature to the configured direct exchange
    async_result = submit_card_dispute_task.apply_async(
        args=[dispute_id, simulate_failure],
        headers=headers,
    )

    logger.info(
        "dispute_task_dispatched",
        extra={
            "dispute_id": dispute_id,
            "celery_task_id": async_result.id,
            "correlation_id": req_id,
        },
    )

    return async_result.id


def revoke_dispute_task(task_id: str) -> None:
    """Issue a remote task revocation broadcast to all active Celery workers.

    Sends a SIGTERM control signal to terminate the worker process if execution
    is actively underway, and instructs workers to reject the task if still buffered.

    Args:
        task_id: Celery task UUID to revoke.
    """
    if not task_id:
        return

    celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
    logger.info("dispute_task_revoked", extra={"celery_task_id": task_id})
