import os
from datetime import datetime, timezone
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


@celery_app.task(name="worker.reconcile_pending_transactions")
def reconcile_pending_transactions() -> dict[str, int]:
    with psycopg.connect(DATABASE_URL) as connection:
        transactions = connection.execute(
            """
                        UPDATE transactions
                        SET status = 'pending', updated_at = now()
                        WHERE status = 'syncing'
                            AND updated_at < now() - interval '60 seconds';

            SELECT id, idempotency_key
            FROM transactions
            WHERE status IN ('pending', 'unknown')
              AND (next_retry_at IS NULL OR next_retry_at <= now())
            ORDER BY created_at
            LIMIT 100
            """
        ).fetchall()

    for transaction_id, idempotency_key in transactions:
        sync_transaction_status.delay(str(transaction_id), idempotency_key)

    return {"enqueued": len(transactions)}


@celery_app.task(
    bind=True,
    name="worker.sync_transaction_status",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_transaction_status(self, transaction_id: str, idempotency_key: str) -> dict[str, str]:
    with psycopg.connect(DATABASE_URL) as connection:
        transaction = connection.execute(
            "SELECT amount, currency, provider_transaction_id, status FROM transactions WHERE id = %s",
            (UUID(transaction_id),),
        ).fetchone()
        if transaction is None:
            return {"status": "missing"}

        amount, currency, provider_transaction_id, status = transaction
        if status in ("succeeded", "failed"):
            return {"status": status}
        if status == "syncing":
            return {"status": "already_processing"}

        connection.execute(
            "UPDATE transactions SET status = %s, updated_at = %s WHERE id = %s",
            ("syncing", datetime.now(timezone.utc), UUID(transaction_id)),
        )
        connection.commit()

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

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{PROVIDER_URL}/provider/transactions",
                    headers={"Idempotency-Key": idempotency_key},
                    json={"amount": int(amount), "currency": currency, "failure_mode": "success"},
                )
            if 400 <= response.status_code < 500:
                connection.execute(
                    "UPDATE transactions SET status = %s, sync_attempts = %s, last_error = %s, updated_at = %s WHERE id = %s",
                    ("failed", attempt_number, response.text, datetime.now(timezone.utc), UUID(transaction_id)),
                )
                connection.execute(
                    "UPDATE sync_attempts SET outcome = %s, provider_http_status = %s, error_message = %s, finished_at = %s WHERE id = %s",
                    ("permanent_failure", response.status_code, response.text, datetime.now(timezone.utc), attempt_id),
                )
                connection.commit()
                return {"status": "failed"}
            response.raise_for_status()
            provider = response.json()
            connection.execute(
                "UPDATE transactions SET provider_transaction_id = %s, provider_status = %s, status = %s, sync_attempts = %s, last_synced_at = %s, last_error = NULL, updated_at = %s WHERE id = %s",
                (provider["provider_transaction_id"], provider["status"], "succeeded", attempt_number, started_at, started_at, UUID(transaction_id)),
            )
            outcome = "success"
            result = {"status": "succeeded"}
        except (httpx.HTTPError, OSError) as exc:
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
            raise self.retry(exc=exc, countdown=2**attempt_number)

        connection.execute(
            "UPDATE sync_attempts SET outcome = %s, provider_http_status = %s, finished_at = %s WHERE id = %s",
            (outcome, 200, datetime.now(timezone.utc), attempt_id),
        )
        connection.commit()
        return result
