"""Tests for the FastAPI transaction API and its request/validation behavior."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.main import create_app
from app.routes import get_session
from app.schemas import AccountCreate, TransactionCreate


@pytest.fixture
def client():
    """Create a FastAPI test client for each test case."""
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_returns_request_id(client):
    """The health endpoint should echo the request id and return a 200 response."""
    response = client.get("/health", headers={"X-Request-ID": "test-request-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-request-1"


def test_accounts_list_endpoint_is_registered(client):
    """The OpenAPI schema should expose the account listing endpoint."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["paths"]["/accounts"]["get"]["responses"]["200"]


def test_transaction_creation_stays_pending_when_enqueue_fails(monkeypatch):
    """A failed enqueue should not make the API reject a valid transaction request."""
    account_id = uuid4()
    now = datetime.now(timezone.utc)

    class FakeSession:
        async def scalar(self, query):
            return None

        async def get(self, model, identifier):
            return type("Account", (), {"id": account_id, "currency": "USD"})()

        def add(self, transaction):
            transaction.id = uuid4()
            transaction.sync_attempts = 0
            transaction.created_at = now
            transaction.updated_at = now

        async def commit(self):
            return None

        async def refresh(self, transaction):
            return None

    app = create_app()
    app.dependency_overrides[get_session] = lambda: FakeSession()
    monkeypatch.setattr(
        "app.routes.enqueue_transaction_sync",
        lambda transaction_id, idempotency_key: (_ for _ in ()).throw(
            ConnectionError("RabbitMQ is unavailable")
        ),
    )

    with TestClient(app) as test_client:
        response = test_client.post(
            "/transactions",
            headers={"Idempotency-Key": "enqueue-failure-test"},
            json={"account_id": str(account_id), "amount": 1000, "currency": "USD"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_account_model_normalizes_currency():
    """Account payloads should be canonicalized to uppercase currency codes."""
    account = AccountCreate(external_reference="acct-1", currency="usd")

    assert account.currency == "USD"
    assert account.balance == 0


def test_money_values_use_minor_unit_integers():
    """Input values should remain integer minor-unit representation without conversion."""
    account = AccountCreate(external_reference="acct-2", balance=1050, currency="USD")
    transaction = TransactionCreate(
        account_id="11111111-1111-1111-1111-111111111111",
        amount=250,
        currency="USD",
    )

    assert account.balance == 1050
    assert transaction.amount == 250


def test_transaction_model_rejects_non_positive_amount():
    """Transaction amounts must be strictly positive to prevent invalid records."""
    with pytest.raises(ValidationError):
        TransactionCreate(
            account_id="11111111-1111-1111-1111-111111111111",
            amount=0,
            currency="USD",
        )
