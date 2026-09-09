"""Regression tests for retry behavior and durable transaction status updates."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from celery.exceptions import Retry
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from app.config import get_settings
from app.models import Account, Base, SyncAttempt, Transaction
from services.provider_api.app import app as provider_app
from services.provider_api.app import attempts, transactions
from services.worker import tasks as worker_tasks


@pytest.fixture
def postgres_db():
    """Start a disposable PostgreSQL instance and initialize the schema for each test."""
    with PostgresContainer(
        "postgres:16",
        username="celery",
        password="celery-dev-password",
        dbname="transactions",
    ) as container:
        engine = create_engine(container.get_connection_url(driver="psycopg"))
        Base.metadata.create_all(bind=engine)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def configured_postgres(postgres_db, monkeypatch):
    """Point application and worker configuration at the disposable PostgreSQL instance."""
    sync_url = postgres_db.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    monkeypatch.setenv("DATABASE_URL", async_url)
    get_settings.cache_clear()
    assert get_settings().database_url == async_url
    monkeypatch.setattr(worker_tasks, "DATABASE_URL", sync_url)
    monkeypatch.setattr(worker_tasks, "PROVIDER_URL", "http://testserver")
    try:
        yield postgres_db
    finally:
        get_settings.cache_clear()


@pytest.fixture
def provider_api():
    """Start the provider FastAPI application for the duration of a test."""
    attempts.clear()
    transactions.clear()
    with TestClient(provider_app) as client:
        yield client
    attempts.clear()
    transactions.clear()


class SequenceProviderClient:
    """ASGI-backed provider client that always returns the next deterministic failure/success."""

    def __init__(self, provider_client: TestClient, failure_mode: str = "sequence") -> None:
        self.provider_client = provider_client
        self.failure_mode = failure_mode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
        payload = dict(json)
        payload["failure_mode"] = self.failure_mode
        return self.provider_client.post(url, headers=headers, json=payload)


def _insert_transaction(engine, idempotency_key: str, *, status: str = "pending") -> str:
    with Session(engine) as session:
        account = Account(external_reference=f"acct-{uuid4()}", currency="USD", balance=0)
        session.add(account)
        session.commit()
        session.refresh(account)

        transaction = Transaction(
            account_id=account.id,
            idempotency_key=idempotency_key,
            amount=100,
            currency="USD",
            status=status,
        )
        session.add(transaction)
        session.commit()
        session.refresh(transaction)
        return str(transaction.id)


def test_sync_transaction_status_retries_on_retryable_provider_errors(
    configured_postgres, provider_api, monkeypatch, caplog
):
    """The provider's sequential failure mode should require retries and end in a persisted success."""
    attempts.clear()
    transactions.clear()
    caplog.set_level(logging.INFO, logger="services.worker.tasks")
    monkeypatch.setattr(worker_tasks.random, "uniform", lambda lower, upper: upper / 2)
    transaction_id = _insert_transaction(configured_postgres, "retry-key")
    monkeypatch.setattr(
        worker_tasks.httpx,
        "Client",
        lambda *args, **kwargs: SequenceProviderClient(provider_api, failure_mode="sequence"),
    )

    with pytest.raises(Retry):
        worker_tasks.sync_transaction_status.run(transaction_id, "retry-key")

    retry_record = next(
        record for record in caplog.records if hasattr(record, "retry_countdown")
    )
    assert retry_record.retry_countdown == 3.0

    with Session(configured_postgres) as session:
        row = session.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        assert row.status == "unknown"
        assert row.sync_attempts == 1
        assert row.last_error is not None
        assert attempts["retry-key"] == 1

    with pytest.raises(Retry):
        worker_tasks.sync_transaction_status.run(transaction_id, "retry-key")

    with Session(configured_postgres) as session:
        row = session.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        assert row.status == "unknown"
        assert row.sync_attempts == 2
        assert row.last_error is not None
        assert attempts["retry-key"] == 2

    result = worker_tasks.sync_transaction_status.run(transaction_id, "retry-key")
    assert result == {"status": "succeeded"}

    with Session(configured_postgres) as session:
        row = session.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        assert row.status == "succeeded"
        assert row.provider_status == "succeeded"
        assert row.sync_attempts == 3
        assert row.last_error is None
        assert attempts["retry-key"] == 3
        history = session.execute(
            select(SyncAttempt)
            .where(SyncAttempt.transaction_id == transaction_id)
            .order_by(SyncAttempt.attempt_number)
        ).scalars().all()
        assert [attempt.outcome for attempt in history] == [
            "retryable_failure",
            "retryable_failure",
            "success",
        ]
    metrics = [
        record
        for record in caplog.records
        if record.getMessage().startswith("transaction_sync_metrics")
    ]
    assert any(
        record.attempts == 3
        and record.retry_count == 2
        and record.duration_ms >= 0
        and record.final_outcome == "success"
        for record in metrics
    )


def test_sync_transaction_status_marks_transaction_failed_for_permanent_provider_error(configured_postgres, provider_api, monkeypatch):
    """Permanent provider rejection must be recorded as a terminal failure without a retry."""
    attempts.clear()
    transactions.clear()
    transaction_id = _insert_transaction(configured_postgres, "permanent-key")
    monkeypatch.setattr(
        worker_tasks.httpx,
        "Client",
        lambda *args, **kwargs: SequenceProviderClient(provider_api, failure_mode="permanent"),
    )

    result = worker_tasks.sync_transaction_status.run(transaction_id, "permanent-key")

    assert result == {"status": "failed"}
    with Session(configured_postgres) as session:
        row = session.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        assert row.status == "failed"
        assert row.sync_attempts == 1
        assert row.last_error is not None
        assert "permanent provider rejection" in row.last_error.lower()


def test_sync_transaction_status_marks_retry_exhaustion_as_terminal_failure(
    configured_postgres, provider_api, monkeypatch
):
    """An always-retryable provider must become a terminal local failure at the retry limit."""
    attempts.clear()
    transactions.clear()
    transaction_id = _insert_transaction(configured_postgres, "exhausted-key")
    monkeypatch.setattr(
        worker_tasks.httpx,
        "Client",
        lambda *args, **kwargs: SequenceProviderClient(provider_api, failure_mode="disconnect"),
    )

    worker_tasks.sync_transaction_status.push_request(
        retries=worker_tasks.sync_transaction_status.max_retries,
        id="exhausted-task",
    )
    try:
        result = worker_tasks.sync_transaction_status.run(transaction_id, "exhausted-key")
    finally:
        worker_tasks.sync_transaction_status.pop_request()

    assert result == {"status": "failed"}
    with Session(configured_postgres) as session:
        row = session.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        assert row.status == "failed"
        assert row.sync_attempts == 1
        assert row.next_retry_at is None
        attempt = session.execute(
            select(SyncAttempt).where(SyncAttempt.transaction_id == transaction_id)
        ).scalar_one()
        assert attempt.outcome == "retry_exhausted"


def test_duplicate_delivery_skips_terminal_transaction(
    configured_postgres, provider_api, monkeypatch
):
    """A duplicate delivery after success must not call the provider again."""
    attempts.clear()
    transactions.clear()
    transaction_id = _insert_transaction(configured_postgres, "duplicate-key")
    monkeypatch.setattr(
        worker_tasks.httpx,
        "Client",
        lambda *args, **kwargs: SequenceProviderClient(provider_api, failure_mode="success"),
    )

    assert worker_tasks.sync_transaction_status.run(transaction_id, "duplicate-key") == {
        "status": "succeeded"
    }
    assert worker_tasks.sync_transaction_status.run(transaction_id, "duplicate-key") == {
        "status": "succeeded"
    }
    assert attempts["duplicate-key"] == 1

    with Session(configured_postgres) as session:
        history = session.execute(
            select(SyncAttempt).where(SyncAttempt.transaction_id == transaction_id)
        ).scalars().all()
        assert len(history) == 1


def test_reconcile_pending_transactions_redelivers_stale_worker_task(
    configured_postgres, monkeypatch
):
    """Reconciliation must reset stale syncing work and publish it again."""
    transaction_id = _insert_transaction(configured_postgres, "redelivery-key", status="syncing")
    with Session(configured_postgres) as session:
        row = session.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        session.commit()

    published = []

    def publish(*, args, task_id):
        published.append((args, task_id))

    monkeypatch.setattr(worker_tasks.sync_transaction_status, "apply_async", publish)

    result = worker_tasks.reconcile_pending_transactions.run()

    assert result == {"enqueued": 1}
    assert published == [([transaction_id, "redelivery-key"], transaction_id)]
    with Session(configured_postgres) as session:
        row = session.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        assert row.status == "pending"
