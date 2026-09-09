"""Celery client helpers for enqueueing a transaction synchronization task."""

import os

from celery import Celery

celery_app = Celery(
    "client_api",
    broker=os.getenv("CELERY_BROKER_URL", "amqp://celery:celery-dev-password@localhost:5672//"),
)


def enqueue_transaction_sync(transaction_id: str, idempotency_key: str) -> None:
    """Publish a synchronization task for a specific transaction and idempotency key."""
    celery_app.send_task(
        "worker.sync_transaction_status",
        args=[transaction_id, idempotency_key],
        task_id=transaction_id,
    )
