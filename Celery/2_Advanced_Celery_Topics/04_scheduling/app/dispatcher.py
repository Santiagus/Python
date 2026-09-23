"""Autonomous Celery task dispatcher for the API control plane.

Encapsulates producer-side message dispatching, AMQP queue routing, and correlation ID
tracing without coupling HTTP request handlers to worker domain logic.
"""

from __future__ import annotations

import logging

from app.logging_config import current_request_id
from services.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

RECONCILIATION_TASK_NAME = "services.worker.tasks.reconciliation.reconcile_eod_cutoff"
BACKFILL_TASK_NAME = "services.worker.tasks.backfill.detect_and_backfill_gaps"


def dispatch_reconciliation_cutoff(
    period_date_str: str,
    clearing_variance_cents: int = 0,
) -> str:
    """Publish an asynchronous EOD reconciliation trigger message to RabbitMQ.

    Args:
        period_date_str: Business date string formatted as 'YYYY-MM-DD'.
        clearing_variance_cents: Optional minor-unit discrepancy simulated from external clearing.

    Returns:
        str: Dispatched Celery task ID (UUID string).
    """
    req_id = current_request_id.get() or "unknown"

    # 1. Prepare message payload and AMQP headers with tracing metadata
    task_headers = {
        "request_id": req_id,
        "source": "api_gateway",
    }

    # 2. Dispatch task over RabbitMQ via AMQP 0-9-1
    result = celery_app.send_task(
        RECONCILIATION_TASK_NAME,
        args=[period_date_str, clearing_variance_cents],
        queue="reconciliation",
        routing_key="scheduling.reconciliation",
        headers=task_headers,
    )

    logger.info(
        "reconciliation_task_dispatched",
        extra={
            "task_id": result.id,
            "period_date": period_date_str,
            "clearing_variance_cents": clearing_variance_cents,
            "request_id": req_id,
        },
    )

    return str(result.id)


def dispatch_gap_backfill(
    start_date_str: str | None = None,
    end_date_str: str | None = None,
) -> str:
    """Publish an asynchronous historical gap backfill message to RabbitMQ.

    Args:
        start_date_str: Optional scan range start date string formatted as 'YYYY-MM-DD'.
        end_date_str: Optional scan range end date string formatted as 'YYYY-MM-DD'.

    Returns:
        str: Dispatched Celery task ID (UUID string).
    """
    req_id = current_request_id.get() or "unknown"

    # 1. Prepare message payload and AMQP headers with tracing metadata
    task_headers = {
        "request_id": req_id,
        "source": "api_gateway",
    }

    # 2. Dispatch task over RabbitMQ via AMQP 0-9-1
    result = celery_app.send_task(
        BACKFILL_TASK_NAME,
        args=[start_date_str, end_date_str],
        queue="reconciliation",
        routing_key="scheduling.reconciliation",
        headers=task_headers,
    )

    logger.info(
        "gap_backfill_task_dispatched",
        extra={
            "task_id": result.id,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "request_id": req_id,
        },
    )

    return str(result.id)
