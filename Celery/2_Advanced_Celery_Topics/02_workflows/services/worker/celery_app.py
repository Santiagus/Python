"""Celery worker application instance and configuration.

Configures RabbitMQ as message broker and Redis as result backend for
underwriting canvas workflows (chain, group, chord, and error handlers).
"""

from __future__ import annotations

import os
from celery import Celery

# Broker & backend URLs from environment with fallback defaults
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5673//")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

celery_app = Celery(
    "underwriting_worker",
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
    include=["services.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)


from celery.signals import setup_logging
from typing import Any


@setup_logging.connect
def configure_celery_logging(*args: Any, **kwargs: Any) -> None:
    """Synchronize Celery worker logging with application pretty/JSON formatting."""
    from app.config import settings
    from app.logging_config import configure_logging

    configure_logging(
        level=settings.log_level,
        log_format=settings.effective_log_format,
    )

