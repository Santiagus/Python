"""Celery application configuration and Kombu AMQP routing topology.

Defines the Driver/Protocol Layer using Kombu primitives (Exchange, Queue),
dead-letter exchanges (DLX), worker invariants (acks_late=True, prefetch_multiplier=1),
and context variable correlation ID propagation across worker processes.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Celery, signals
from kombu import Exchange, Queue

from app.config import get_settings
from app.db import init_worker_db
from app.logging_config import current_request_id

logger = logging.getLogger(__name__)
settings = get_settings()

# =============================================================================
# 1. Driver / Protocol Layer: Kombu AMQP Exchanges
# =============================================================================
disputes_exchange = Exchange(settings.disputes_exchange, type="direct", durable=True)
dead_letter_exchange = Exchange(settings.dlx_exchange, type="direct", durable=True)

# =============================================================================
# 2. Driver / Protocol Layer: AMQP Queues with Dead-Lettering
# =============================================================================
task_queues = [
    # Primary Dispute Processing Queue
    Queue(
        settings.disputes_queue,
        exchange=disputes_exchange,
        routing_key=settings.disputes_routing_key,
        queue_arguments={
            "x-dead-letter-exchange": settings.dlx_exchange,
            "x-dead-letter-routing-key": settings.dlq_routing_key,
        },
    ),
    # Dead Letter Queue (Quarantine for Poison Pills & Network Timeouts)
    Queue(
        settings.dlq_queue,
        exchange=dead_letter_exchange,
        routing_key=settings.dlq_routing_key,
    ),
]

# =============================================================================
# 3. Application Layer: Domain Task Routes
# =============================================================================
task_routes = {
    "services.worker.tasks.disputes.submit_card_dispute_task": {
        "queue": settings.disputes_queue,
        "routing_key": settings.disputes_routing_key,
    },
}

# =============================================================================
# 4. Celery App Instance & Runtime Invariants
# =============================================================================
backend_url = settings.celery_result_backend if settings.environment not in ("test", "testing") else None

celery_app = Celery(
    "card_disputes_worker",
    broker=settings.celery_broker_url,
    backend=backend_url,
    include=["services.worker.tasks"],
)

celery_app.conf.update(
    task_queues=task_queues,
    task_routes=task_routes,
    task_default_queue=settings.disputes_queue,
    task_default_exchange=settings.disputes_exchange,
    task_default_routing_key=settings.disputes_routing_key,
    # Serialization safety: strictly JSON primitives
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Operational reliability invariants
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_pool_limit=10,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
)

# Token dictionary for ContextVar cleanup per task
_task_context_tokens: dict[str, Any] = {}


# =============================================================================
# 5. Boot Initialization & Tracing Signals
# =============================================================================
@signals.worker_process_init.connect
def handle_worker_process_init(**kwargs: Any) -> None:
    """Pre-warm process-local database pool upon fork to eliminate first-call cold start."""
    logger.info("worker_process_init_warming_db")
    init_worker_db()


@signals.task_prerun.connect
def handle_task_prerun(sender: Any, task_id: str, task: Any, args: Any, kwargs: Any, **kw: Any) -> None:
    """Extract correlation_id from AMQP task headers and bind to worker ContextVar."""
    # 1. Inspect request headers attached during API dispatcher publish
    headers = getattr(task.request, "headers", None) or {}
    correlation_id = headers.get("correlation_id") or headers.get("request_id") or task_id

    # 2. Bind to ContextVar so worker logs mirror the original HTTP request trace
    token = current_request_id.set(correlation_id)
    _task_context_tokens[task_id] = token

    logger.debug(
        "worker_task_started",
        extra={
            "task_name": task.name,
            "task_id": task_id,
            "correlation_id": correlation_id,
        },
    )


@signals.task_postrun.connect
def handle_task_postrun(
    sender: Any, task_id: str, task: Any, args: Any, kwargs: Any, retval: Any, state: str, **kw: Any
) -> None:
    """Reset ContextVar token upon task completion to prevent context leakage."""
    token = _task_context_tokens.pop(task_id, None)
    if token is not None:
        current_request_id.reset(token)

    logger.debug(
        "worker_task_finished",
        extra={
            "task_name": task.name,
            "task_id": task_id,
            "state": state,
        },
    )
