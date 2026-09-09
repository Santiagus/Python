"""Celery worker tasks for reconciling pending transactions and syncing external status."""

import logging
import os
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import psycopg
from celery import Celery

celery_app = Celery(
    "transaction_worker",
    broker=os.getenv("CELERY_BROKER_URL", "amqp://celery:celery-dev-password@rabbitmq:5672//"),
)
celery_app.conf.beat_schedule = {
    "reconcile-pending-transactions": {
        "task": "worker.reconcile_pending_transactions",
        "schedule": 30.0,
    },
}
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://celery:celery-dev-password@postgres:5432/transactions",
)
PROVIDER_URL = os.getenv("PROVIDER_URL", "http://provider-api:8001")
logger = logging.getLogger(__name__)


def _log_sync_metrics(transaction_id: str, attempt_number: int, started_at: datetime, outcome: str) -> None:
    """Emit the synchronization metrics for one completed worker attempt."""
    duration_ms = round((datetime.now(timezone.utc) - started_at).total_seconds() * 1000, 2)
    logger.info(
        "transaction_sync_metrics transaction_id=%s attempts=%s retry_count=%s duration_ms=%s final_outcome=%s",
        transaction_id,
        attempt_number,
        max(attempt_number - 1, 0),
        duration_ms,
        outcome,
        extra={
            "transaction_id": transaction_id,
            "attempts": attempt_number,
            "retry_count": max(attempt_number - 1, 0),
            "duration_ms": duration_ms,
            "final_outcome": outcome,
        },
    )


@celery_app.task(name="worker.reconcile_pending_transactions")
def reconcile_pending_transactions() -> dict[str, int]:
    """Re-enqueue stale or pending transactions so they are retried by the worker."""
    with psycopg.connect(DATABASE_URL) as connection:
        # Worker loss can leave a row in syncing; make that work eligible again
        # before selecting pending work for republishing.
        connection.execute(
            """
            UPDATE transactions
            SET status = 'pending', updated_at = now()
            WHERE status = 'syncing'
              AND updated_at < now() - interval '60 seconds'
            """
        )
        connection.commit()
        transactions = connection.execute(
            """
            SELECT id, idempotency_key
            FROM transactions
            WHERE status IN ('pending', 'unknown')
              AND (next_retry_at IS NULL OR next_retry_at <= now())
            ORDER BY created_at
            LIMIT 100
            """
        ).fetchall()

    # Publish only identifiers and the idempotency key; the worker reloads the
    # authoritative transaction state when it receives each message.
    for transaction_id, idempotency_key in transactions:
        logger.info(
            "transaction_reconciliation_enqueued transaction_id=%s idempotency_key=%s",
            transaction_id,
            idempotency_key,
            extra={"transaction_id": str(transaction_id), "idempotency_key": idempotency_key},
        )
        sync_transaction_status.apply_async(
            args=[str(transaction_id), idempotency_key],
            task_id=str(transaction_id),
        )

    logger.info("transaction_reconciliation_complete enqueued=%s", len(transactions))
    return {"enqueued": len(transactions)}


@celery_app.task(
    bind=True,
    name="worker.sync_transaction_status",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_transaction_status(self, transaction_id: str, idempotency_key: str) -> dict[str, str]:
    """Synchronize a transaction with the provider, retry transient faults, and log outcomes."""
    logger.info(
        "transaction_sync_started transaction_id=%s idempotency_key=%s",
        transaction_id,
        idempotency_key,
        extra={"transaction_id": transaction_id, "idempotency_key": idempotency_key},
    )
    with psycopg.connect(DATABASE_URL) as connection:
        # Lock the row while deciding whether this delivery owns the work. A
        # duplicate delivery waits for the first delivery, then sees syncing or
        # a terminal status instead of starting a second provider operation.
        transaction = connection.execute(
            "SELECT amount, currency, provider_transaction_id, status FROM transactions WHERE id = %s FOR UPDATE",
            (UUID(transaction_id),),
        ).fetchone()
        if transaction is None:
            logger.warning("transaction_not_found transaction_id=%s", transaction_id)
            return {"status": "missing"}

        amount, currency, provider_transaction_id, status = transaction
        if status in ("succeeded", "failed"):
            logger.info("transaction_sync_skipped_terminal transaction_id=%s status=%s", transaction_id, status)
            return {"status": status}
        if status == "syncing":
            logger.info("transaction_sync_skipped_in_progress transaction_id=%s", transaction_id)
            return {"status": "already_processing"}

        # Commit the claim before calling the remote service so reconciliation
        # can detect work abandoned by a process that dies during the request.
        connection.execute(
            "UPDATE transactions SET status = %s, updated_at = %s WHERE id = %s",
            ("syncing", datetime.now(timezone.utc), UUID(transaction_id)),
        )
        connection.commit()

        # Persist an attempt before the provider call. This makes an in-flight
        # request visible in the audit history even if the worker is terminated.
        attempt_number = connection.execute(
            "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM sync_attempts WHERE transaction_id = %s",
            (UUID(transaction_id),),
        ).fetchone()[0]
        attempt_id = uuid4()
        started_at = datetime.now(timezone.utc)
        connection.execute(
            "INSERT INTO sync_attempts (id, transaction_id, celery_task_id, attempt_number, outcome, started_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (attempt_id, UUID(transaction_id), self.request.id or "unknown", attempt_number, "started", started_at),
        )
        connection.commit()
        logger.info(
            "provider_request_started transaction_id=%s attempt=%s",
            transaction_id,
            attempt_number,
            extra={
                "transaction_id": transaction_id,
                "idempotency_key": idempotency_key,
                "attempt_number": attempt_number,
            },
        )

        try:
            # The same idempotency key is sent on every delivery, allowing the
            # provider to replay an accepted transaction instead of duplicating it.
            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{PROVIDER_URL}/provider/transactions",
                    headers={"Idempotency-Key": idempotency_key},
                    json={"amount": int(amount), "currency": currency, "failure_mode": "sequence"},
                )
            logger.info(
                "provider_response_received transaction_id=%s attempt=%s status_code=%s",
                transaction_id,
                attempt_number,
                response.status_code,
                extra={
                    "transaction_id": transaction_id,
                    "attempt_number": attempt_number,
                    "status_code": response.status_code,
                },
            )
            if 400 <= response.status_code < 500:
                # A client-side provider rejection is terminal for this local
                # transaction and must not consume more Celery retries.
                connection.execute(
                    "UPDATE transactions SET status = %s, sync_attempts = %s, last_error = %s, next_retry_at = NULL, updated_at = %s WHERE id = %s",
                    ("failed", attempt_number, response.text, datetime.now(timezone.utc), UUID(transaction_id)),
                )
                connection.execute(
                    "UPDATE sync_attempts SET outcome = %s, provider_http_status = %s, error_message = %s, finished_at = %s WHERE id = %s",
                    ("permanent_failure", response.status_code, response.text, datetime.now(timezone.utc), attempt_id),
                )
                connection.commit()
                _log_sync_metrics(transaction_id, attempt_number, started_at, "permanent_failure")
                logger.error(
                    "transaction_sync_failed_permanently transaction_id=%s attempt=%s status_code=%s",
                    transaction_id,
                    attempt_number,
                    response.status_code,
                    extra={"transaction_id": transaction_id, "attempt_number": attempt_number, "status_code": response.status_code},
                )
                return {"status": "failed"}
            response.raise_for_status()
            provider = response.json()
            connection.execute(
                "UPDATE transactions SET provider_transaction_id = %s, provider_status = %s, status = %s, sync_attempts = %s, last_synced_at = %s, last_error = NULL, next_retry_at = NULL, updated_at = %s WHERE id = %s",
                (provider["provider_transaction_id"], provider["status"], "succeeded", attempt_number, started_at, started_at, UUID(transaction_id)),
            )
            outcome = "success"
            result = {"status": "succeeded"}
        except (httpx.HTTPError, OSError) as exc:
            # Network and 5xx failures leave the provider result ambiguous, so
            # preserve the error locally before deciding whether to retry.
            connection.execute(
                "UPDATE transactions SET status = %s, sync_attempts = %s, last_error = %s, updated_at = %s WHERE id = %s",
                ("unknown", attempt_number, str(exc), started_at, UUID(transaction_id)),
            )
            outcome = "retryable_failure"
            result = {"status": "retrying"}
            connection.execute(
                "UPDATE sync_attempts SET outcome = %s, error_type = %s, error_message = %s, finished_at = %s WHERE id = %s",
                (outcome, type(exc).__name__, str(exc), datetime.now(timezone.utc), attempt_id),
            )
            connection.commit()
            _log_sync_metrics(transaction_id, attempt_number, started_at, "retrying")
            if self.request.retries >= self.max_retries:
                # Do not schedule another message after Celery's retry budget is
                # exhausted; make the terminal outcome queryable in PostgreSQL.
                connection.execute(
                    "UPDATE transactions SET status = %s, last_error = %s, next_retry_at = NULL, updated_at = %s WHERE id = %s",
                    ("failed", f"retry exhaustion: {exc}", datetime.now(timezone.utc), UUID(transaction_id)),
                )
                connection.execute(
                    "UPDATE sync_attempts SET outcome = %s WHERE id = %s",
                    ("retry_exhausted", attempt_id),
                )
                connection.commit()
                _log_sync_metrics(transaction_id, attempt_number, started_at, "retry_exhausted")
                return {"status": "failed"}

            base_delay = 2**attempt_number
            retry_countdown = base_delay + random.uniform(0, base_delay)
            # Store the same backoff window used by Celery so reconciliation does
            # not immediately republish a retry that is still waiting.
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_countdown)
            connection.execute(
                "UPDATE transactions SET next_retry_at = %s WHERE id = %s",
                (next_retry_at, UUID(transaction_id)),
            )
            connection.commit()
            response = getattr(exc, "response", None)
            if response is not None:
                retry_reason = f"{response.status_code} {response.reason_phrase}"
            else:
                retry_reason = type(exc).__name__
            logger.warning(
                "Task %s retrying transaction_id=%s - %s - Retry in %ss",
                self.request.id or "unknown",
                transaction_id,
                retry_reason,
                retry_countdown,
                extra={
                    "transaction_id": transaction_id,
                    "attempt_number": attempt_number,
                    "error_type": type(exc).__name__,
                    "retry_countdown": retry_countdown,
                },
            )
            raise self.retry(countdown=retry_countdown)

        connection.execute(
            # Finalize the audit row only after the transaction projection and
            # provider result have been accepted by the database.
            "UPDATE sync_attempts SET outcome = %s, provider_http_status = %s, finished_at = %s WHERE id = %s",
            (outcome, 200, datetime.now(timezone.utc), attempt_id),
        )
        connection.commit()
        _log_sync_metrics(transaction_id, attempt_number, started_at, outcome)
        logger.info(
            "transaction_sync_succeeded transaction_id=%s provider_transaction_id=%s attempt=%s",
            transaction_id,
            provider["provider_transaction_id"],
            attempt_number,
            extra={
                "transaction_id": transaction_id,
                "provider_transaction_id": provider["provider_transaction_id"],
                "attempt_number": attempt_number,
            },
        )
        return result
