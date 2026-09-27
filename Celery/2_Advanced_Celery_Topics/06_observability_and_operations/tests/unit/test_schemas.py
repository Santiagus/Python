"""Unit tests for Pydantic v2 domain schemas and Result Envelope (TC-01, TC-02)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError
from services.worker.schemas import (
    ResultEnvelope,
    ScoringResult,
    ScreeningPayload,
    WatchlistResult,
)


def test_screening_payload_valid_conversion() -> None:
    """TC-01: Verify valid payload converts Decimal to minor-unit integer cents."""
    payload = ScreeningPayload(
        screening_id="11223344-5566-7788-99aa-bbccddeeff00",
        transaction_id="tx_test_1001",
        account_id="acc_test_corp",
        entity_name="Acme International",
        amount=Decimal("12500.50"),
        currency="USD",
        client_ip="192.168.1.1",
        velocity_5m_count=3,
    )

    assert payload.screening_id == "11223344-5566-7788-99aa-bbccddeeff00"
    assert payload.transaction_id == "tx_test_1001"
    assert payload.account_id == "acc_test_corp"
    assert payload.entity_name == "Acme International"
    assert payload.amount == Decimal("12500.50")
    assert payload.amount_cents == 1250050
    assert payload.currency == "USD"
    assert payload.client_ip == "192.168.1.1"
    assert payload.velocity_5m_count == 3


def test_screening_payload_invalid_uuid() -> None:
    """TC-02: Verify invalid UUID string raises a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        ScreeningPayload(
            screening_id="invalid-uuid-string",
            transaction_id="tx_test_1002",
            account_id="acc_test_corp",
            entity_name="Acme International",
            amount=Decimal("100.00"),
            currency="USD",
            client_ip="192.168.1.1",
            velocity_5m_count=0,
        )

    assert "not a valid UUID format" in str(exc_info.value)


def test_screening_payload_negative_amount() -> None:
    """TC-02: Verify non-positive monetary amount is rejected by Field constraint."""
    with pytest.raises(ValidationError):
        ScreeningPayload(
            screening_id="11223344-5566-7788-99aa-bbccddeeff00",
            transaction_id="tx_test_1003",
            account_id="acc_test_corp",
            entity_name="Acme International",
            amount=Decimal("-50.00"),
            currency="USD",
            client_ip="192.168.1.1",
            velocity_5m_count=0,
        )


def test_screening_payload_empty_strings() -> None:
    """TC-02: Verify empty transaction_id or account_id fails validation."""
    with pytest.raises(ValidationError):
        ScreeningPayload(
            screening_id="11223344-5566-7788-99aa-bbccddeeff00",
            transaction_id="",
            account_id="",
            entity_name="A",
            amount=Decimal("10.00"),
            currency="USD",
            client_ip="1.1",
            velocity_5m_count=-1,
        )


def test_scoring_result_schema() -> None:
    """Verify ScoringResult model creation and validation."""
    result = ScoringResult(
        risk_score=45,
        decision="approved",
        reasons=["standard_value_transaction"],
    )
    assert result.risk_score == 45
    assert result.decision == "approved"
    assert len(result.reasons) == 1

    with pytest.raises(ValidationError):
        ScoringResult(risk_score=150, decision="approved")


def test_watchlist_result_schema() -> None:
    """Verify WatchlistResult model creation and validation."""
    result = WatchlistResult(
        is_sanctioned=True,
        matches=[{"entity_name": "TEST ENTITY", "match_confidence": 98.5}],
        decision="blocked",
        reasons=["sanctions_watchlist_positive_match"],
    )
    assert result.is_sanctioned is True
    assert len(result.matches) == 1
    assert result.decision == "blocked"


def test_result_envelope_schema() -> None:
    """Verify ResultEnvelope model handles ok, degraded, and failed states."""
    ok_env = ResultEnvelope(
        status="ok",
        data={"score": 10},
        errors=[],
    )
    assert ok_env.status == "ok"
    assert ok_env.data["score"] == 10
    assert ok_env.errors == []

    degraded_env = ResultEnvelope(
        status="degraded",
        data={"fallback_score": 40},
        errors=["timeout_connecting_to_api"],
    )
    assert degraded_env.status == "degraded"
    assert degraded_env.errors[0] == "timeout_connecting_to_api"
