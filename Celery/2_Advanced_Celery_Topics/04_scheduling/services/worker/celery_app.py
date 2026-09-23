"""Celery application configuration and lifecycle signal management for Module 04 Scheduling.

Enforces AMQP 0-9-1 queue routing, strict JSON serialization, explicit timezone settings,
and connection warm-up hooks at worker child process initialization.
"""

from __future__ import annotations

import logging

from celery import Celery, signals
from kombu import Exchange, Queue

from app.config import get_settings
from app.db import close_db_engine, init_db
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
    task_queues=queues,
    task_default_queue="reconciliation",
    task_default_exchange="scheduling.direct",
    task_default_routing_key="scheduling.reconciliation",
    task_routes={
        "services.worker.tasks.reconciliation.*": {
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
    import asyncio

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
