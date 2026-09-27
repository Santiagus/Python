"""Unit tests for Pydantic v2 domain schemas and minor-unit financial arithmetic."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    DisputeCancelResponse,
    DisputeCreateRequest,
    DisputeReason,
    DisputeResponse,
    DisputeRetryResponse,
    DisputeStatus,
    from_cents,
    to_cents,
)


def test_to_cents_precision() -> None:
    """Verify Decimal to integer cents conversion with banking rounding."""
    assert to_cents(Decimal("149.99")) == 14999
    assert to_cents(Decimal("0.01")) == 1
    assert to_cents(Decimal("0.005")) == 1  # ROUND_HALF_UP rounds 0.005 to 0.01
    assert to_cents(Decimal("100.00")) == 10000


def test_from_cents_precision() -> None:
    """Verify integer cents to Decimal dollars conversion."""
    assert from_cents(14999) == Decimal("149.99")
    assert from_cents(1) == Decimal("0.01")
    assert from_cents(10000) == Decimal("100.00")


def test_dispute_create_request_valid() -> None:
    """Verify valid DisputeCreateRequest schema instantiation and property."""
    payload = DisputeCreateRequest(
        transaction_id="tx_12345",
        card_token="tok_card_secret_123",
        card_last_four="4242",
        amount=Decimal("89.50"),
        currency="USD",
        reason=DisputeReason.fraudulent,
        evidence_notes="Cardholder confirmed unauthorized transaction.",
    )
    assert payload.transaction_id == "tx_12345"
    assert payload.card_token == "tok_card_secret_123"
    assert payload.card_last_four == "4242"
    assert payload.amount == Decimal("89.50")
    assert payload.currency == "USD"
    assert payload.reason == DisputeReason.fraudulent
    assert payload.evidence_notes == "Cardholder confirmed unauthorized transaction."
    assert payload.amount_cents == 8950


def test_dispute_create_request_invalid_card_last_four() -> None:
    """Verify that card_last_four must be exactly 4 digits."""
    with pytest.raises(ValidationError) as exc_info:
        DisputeCreateRequest(
            transaction_id="tx_123",
            card_token="tok_card_secret_123",
            card_last_four="424",  # 3 digits
            amount=Decimal("10.00"),
            reason=DisputeReason.unrecognized,
        )
    assert "card_last_four" in str(exc_info.value)

    with pytest.raises(ValidationError):
        DisputeCreateRequest(
            transaction_id="tx_123",
            card_token="tok_card_secret_123",
            card_last_four="abcd",  # Non-numeric
            amount=Decimal("10.00"),
            reason=DisputeReason.unrecognized,
        )


def test_dispute_create_request_invalid_amount() -> None:
    """Verify that amount must be strictly greater than zero and have at most 2 decimal places."""
    with pytest.raises(ValidationError):
        DisputeCreateRequest(
            transaction_id="tx_123",
            card_token="tok_card_secret_123",
            card_last_four="1234",
            amount=Decimal("0.00"),  # Zero not allowed
            reason=DisputeReason.duplicate,
        )

    with pytest.raises(ValidationError):
        DisputeCreateRequest(
            transaction_id="tx_123",
            card_token="tok_card_secret_123",
            card_last_four="1234",
            amount=Decimal("-15.00"),  # Negative not allowed
            reason=DisputeReason.duplicate,
        )

    with pytest.raises(ValidationError):
        DisputeCreateRequest(
            transaction_id="tx_123",
            card_token="tok_card_secret_123",
            card_last_four="1234",
            amount=Decimal("10.005"),  # Exceeds 2 decimal places
            reason=DisputeReason.duplicate,
        )


def test_dispute_create_request_invalid_reason() -> None:
    """Verify that invalid dispute reasons are rejected."""
    with pytest.raises(ValidationError):
        DisputeCreateRequest(
            transaction_id="tx_123",
            card_token="tok_card_secret_123",
            card_last_four="1234",
            amount=Decimal("20.00"),
            reason="invalid_reason_code",  # type: ignore[arg-type]
        )


def test_dispute_create_request_invalid_currency() -> None:
    """Verify that currency must be a 3-letter uppercase ISO code."""
    with pytest.raises(ValidationError):
        DisputeCreateRequest(
            transaction_id="tx_123",
            card_token="tok_card_secret_123",
            card_last_four="1234",
            amount=Decimal("20.00"),
            currency="usd",  # Lowercase not allowed
            reason=DisputeReason.subscription_cancelled,
        )


def test_dispute_response_model() -> None:
    """Verify full DisputeResponse model instantiation."""
    now = datetime.now(timezone.utc)
    dispute_id = uuid4()
    resp = DisputeResponse(
        id=dispute_id,
        transaction_id="tx_999",
        card_token="tok_card_999",
        card_last_four="9999",
        amount_cents=1999,
        amount=Decimal("19.99"),
        currency="USD",
        reason="goods_not_received",
        status=DisputeStatus.processing,
        celery_task_id="task_abc",
        network_reference_id=None,
        attempt_count=1,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    assert resp.id == dispute_id
    assert resp.status == DisputeStatus.processing
    assert resp.amount_cents == 1999
    assert resp.amount == Decimal("19.99")
    assert resp.network_reference_id is None


def test_dispute_cancel_response_model() -> None:
    """Verify DisputeCancelResponse defaults and fields."""
    dispute_id = uuid4()
    resp = DisputeCancelResponse(
        id=dispute_id,
        revoked_task_id="task_revoked_123",
    )
    assert resp.id == dispute_id
    assert resp.status == DisputeStatus.cancelled
    assert resp.revoked_task_id == "task_revoked_123"
    assert "successfully revoked" in resp.message


def test_dispute_retry_response_model() -> None:
    """Verify DisputeRetryResponse fields and status."""
    dispute_id = uuid4()
    resp = DisputeRetryResponse(
        id=dispute_id,
        attempt_count=2,
        celery_task_id="task_new_retry",
    )
    assert resp.id == dispute_id
    assert resp.status == DisputeStatus.processing
    assert resp.attempt_count == 2
    assert resp.celery_task_id == "task_new_retry"
    assert "re-queued" in resp.message
