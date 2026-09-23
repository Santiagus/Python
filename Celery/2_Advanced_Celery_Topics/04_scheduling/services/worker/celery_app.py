"""Celery application configuration and lifecycle signal management for Module 04 Scheduling.

Enforces AMQP 0-9-1 queue routing, strict JSON serialization, explicit timezone settings,
connection warm-up hooks at worker child process initialization, and pretty development logging.
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import Token
from typing import Any

from celery import Celery, signals
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import get_settings
from app.db import close_db_engine, init_db
from app.logging_config import (
    PrettyDevFormatter,
    RequestContextFilter,
    current_request_id,
)
from services.worker.locks import close_redis_client

logger = logging.getLogger(__name__)

settings = get_settings()

# 1. Instantiate Celery Application
celery_app = Celery("scheduling_platform")

# 2. Driver / Protocol Layer: Kombu Exchanges & Queues
scheduling_exchange = Exchange("scheduling.direct", type="direct", durable=True)

queues = (
    Queue(
        "reconciliation",
        exchange=scheduling_exchange,
        routing_key="scheduling.reconciliation",
        durable=True,
    ),
    Queue(
        "cleanup",
        exchange=scheduling_exchange,
        routing_key="scheduling.cleanup",
        durable=True,
    ),
)

# 3. Configure Celery Application Settings
celery_app.conf.update(
    broker_url=settings.rabbitmq_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.celery_timezone,
    enable_utc=True,
    beat_scheduler="services.worker.beat_lock.LeaderElectedScheduler",
    beat_schedule={
        "eod-banking-cutoff": {
            "task": "services.worker.tasks.reconciliation.reconcile_eod_cutoff",
            "schedule": crontab(hour=17, minute=0, day_of_week="mon-fri"),
            "options": {
                "queue": "reconciliation",
                "routing_key": "scheduling.reconciliation",
            },
        },
        "hourly-gap-detector": {
            "task": "services.worker.tasks.backfill.detect_and_backfill_gaps",
            "schedule": crontab(minute=30),
            "options": {
                "queue": "reconciliation",
                "routing_key": "scheduling.reconciliation",
            },
        },
        "nightly-idempotency-cleanup": {
            "task": "services.worker.tasks.cleanup.purge_expired_records",
            "schedule": crontab(hour=2, minute=0),
            "options": {
                "queue": "cleanup",
                "routing_key": "scheduling.cleanup",
            },
        },
    },
    task_queues=queues,
    task_default_queue="reconciliation",
    task_default_exchange="scheduling.direct",
    task_default_routing_key="scheduling.reconciliation",
    task_routes={
        "services.worker.tasks.reconciliation.*": {
            "queue": "reconciliation",
            "routing_key": "scheduling.reconciliation",
        },
        "services.worker.tasks.backfill.*": {
            "queue": "reconciliation",
            "routing_key": "scheduling.reconciliation",
        },
        "services.worker.tasks.cleanup.*": {
            "queue": "cleanup",
            "routing_key": "scheduling.cleanup",
        },
    },
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Active ContextVar tokens per task ID to prevent context leakage across task invocations
_task_context_tokens: dict[str, Token[str | None]] = {}


# =============================================================================
# 4. Celery Logging Configuration Signals
# =============================================================================
@signals.after_setup_logger.connect
def setup_celery_logger(logger: logging.Logger, **kwargs: object) -> None:
    """Attach RequestContextFilter and PrettyDevFormatter to Celery root logger."""
    for handler in logger.handlers:
        handler.addFilter(RequestContextFilter())
        handler.setFormatter(PrettyDevFormatter())


@signals.after_setup_task_logger.connect
def setup_celery_task_logger(logger: logging.Logger, **kwargs: object) -> None:
    """Attach RequestContextFilter and PrettyDevFormatter to Celery task logger."""
    for handler in logger.handlers:
        handler.addFilter(RequestContextFilter())
        handler.setFormatter(PrettyDevFormatter())


# =============================================================================
# 5. Distributed Tracing & Task ContextVar Signals
# =============================================================================
@signals.task_prerun.connect
def handle_task_prerun(
    sender: Any,
    task_id: str,
    task: Any,
    args: Any,
    kwargs: Any,
    **kw: object,
) -> None:
    """Extract correlation_id from task headers and bind to worker ContextVar."""
    request_headers = getattr(task.request, "headers", None) or {}
    correlation_id = request_headers.get("correlation_id") or request_headers.get("request_id") or task_id
    token = current_request_id.set(correlation_id)
    _task_context_tokens[task_id] = token
    logger.debug(
        "worker_task_started",
        extra={
            "task_name": getattr(task, "name", "unknown"),
            "task_id": task_id,
            "correlation_id": correlation_id,
        },
    )


@signals.task_postrun.connect
def handle_task_postrun(
    sender: Any,
    task_id: str,
    task: Any,
    args: Any,
    kwargs: Any,
    retval: Any,
    state: str,
    **kw: object,
) -> None:
    """Reset ContextVar token upon task completion to prevent context leakage."""
    token = _task_context_tokens.pop(task_id, None)
    if token is not None:
        current_request_id.reset(token)
    logger.debug(
        "worker_task_finished",
        extra={
            "task_name": getattr(task, "name", "unknown"),
            "task_id": task_id,
            "state": state,
        },
    )


# =============================================================================
# 6. Worker Lifecycle Signals
# =============================================================================
@signals.worker_process_init.connect
def on_worker_process_init(**kwargs: object) -> None:
    """Warm database pool and logging context when worker child process forks.

    Prevents connection pool sharing across fork boundaries and minimizes first-call latency.
    """
    logger.info("Initializing worker process: warming database connection pool")
    init_db(is_worker=True)


@signals.worker_process_shutdown.connect
def on_worker_process_shutdown(**kwargs: object) -> None:
    """Cleanly dispose of database and Redis pools on worker process termination."""
    logger.info("Disposing worker process resources")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(close_db_engine())
        else:
            loop.run_until_complete(close_db_engine())
    except Exception as exc:
        logger.warning("Worker shutdown cleanup error: %s", exc)
    finally:
        close_redis_client()
