"""Unit tests for Pydantic v2 schemas and validation models in shared/schemas.py."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared.schemas import (
    BankDisburseRequest,
    BankDisburseResponse,
    LedgerEntryCreate,
    WireAuditLogCreate,
    WireCreateRequest,
    WireResponse,
    WireTaskPayload,
    mask_account_number,
)


def test_mask_account_number() -> None:
    """Verify bank account masking logic preserves only last 4 characters."""
    # 1. Standard account number
    assert mask_account_number("1234567890") == "******7890"
    assert mask_account_number("  9876543210  ") == "******3210"

    # 2. Short account number (<= 4 chars)
    assert mask_account_number("1234") == "******1234"
    assert mask_account_number("99") == "******99"


def test_wire_create_request_valid() -> None:
    """Verify successful validation of WireCreateRequest and amount_cents calculation."""
    req = WireCreateRequest(
        client_id="CORP-001",
        amount=Decimal("1250000.50"),
        currency="usd",
        beneficiary_account="9876543210",
        routing_number="121000358",
        swift_bic="chasus33xxx",
    )

    # 1. Assert field attributes and validators
    assert req.client_id == "CORP-001"
    assert req.amount == Decimal("1250000.50")
    assert req.currency == "USD"
    assert req.beneficiary_account == "9876543210"
    assert req.routing_number == "121000358"
    assert req.swift_bic == "CHASUS33XXX"
    assert req.amount_cents == 125000050


def test_wire_create_request_invalid_cases() -> None:
    """Verify validation errors on non-positive amounts, malformed routing numbers, and BIC codes."""
    # 1. Non-positive amount
    with pytest.raises(ValidationError):
        WireCreateRequest(
            client_id="CORP-001",
            amount=Decimal("0.00"),
            currency="USD",
            beneficiary_account="9876543210",
            routing_number="121000358",
            swift_bic="CHASUS33XXX",
        )

    # 2. Negative amount
    with pytest.raises(ValidationError):
        WireCreateRequest(
            client_id="CORP-001",
            amount=Decimal("-100.00"),
            currency="USD",
            beneficiary_account="9876543210",
            routing_number="121000358",
            swift_bic="CHASUS33XXX",
        )

    # 3. Invalid routing number (less than 9 digits)
    with pytest.raises(ValidationError):
        WireCreateRequest(
            client_id="CORP-001",
            amount=Decimal("100.00"),
            currency="USD",
            beneficiary_account="9876543210",
            routing_number="12345",
            swift_bic="CHASUS33XXX",
        )

    # 4. Invalid SWIFT BIC (too short)
    with pytest.raises(ValidationError):
        WireCreateRequest(
            client_id="CORP-001",
            amount=Decimal("100.00"),
            currency="USD",
            beneficiary_account="9876543210",
            routing_number="121000358",
            swift_bic="SHORT",
        )

    # 5. Non-string currency and swift_bic
    with pytest.raises(ValidationError):
        WireCreateRequest(
            client_id="CORP-001",
            amount=Decimal("100.00"),
            currency=123,  # type: ignore[arg-type]
            beneficiary_account="9876543210",
            routing_number="121000358",
            swift_bic="CHASUS33XXX",
        )

    with pytest.raises(ValidationError):
        WireCreateRequest(
            client_id="CORP-001",
            amount=Decimal("100.00"),
            currency="USD",
            beneficiary_account="9876543210",
            routing_number="121000358",
            swift_bic=999,  # type: ignore[arg-type]
        )


def test_wire_response_schema() -> None:
    """Verify WireResponse instantiation and serialization."""
    wire_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    resp = WireResponse(
        wire_id=wire_id,
        client_id="CORP-001",
        amount_cents=100000,
        currency="USD",
        sender_account_mask="******1111",
        beneficiary_account_mask="******2222",
        routing_number="121000358",
        swift_bic="CHASUS33XXX",
        status="processing",
        delivery_attempts=1,
        redelivered_flag=False,
        bank_reference_id=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
        settled_at=None,
    )

    # 1. Assert values
    assert resp.wire_id == wire_id
    assert resp.amount_cents == 100000
    assert resp.status == "processing"
    assert resp.bank_reference_id is None


def test_wire_task_payload() -> None:
    """Verify WireTaskPayload validation and extra field ignoring."""
    wire_id = str(uuid.uuid4())
    data = {
        "wire_id": wire_id,
        "client_id": "CORP-001",
        "idempotency_key": "idemp-abc-123",
        "amount_cents": 50000,
        "currency": "USD",
        "sender_account_mask": "******1111",
        "beneficiary_account_mask": "******2222",
        "routing_number": "121000358",
        "swift_bic": "CHASUS33XXX",
        "disbursement_token": "tok_sec_9999",
        "unneeded_field": "ignored",
    }
    payload = WireTaskPayload.model_validate(data)

    # 1. Assert values
    assert payload.wire_id == wire_id
    assert payload.amount_cents == 50000
    assert payload.disbursement_token == "tok_sec_9999"


def test_bank_disburse_request_and_response() -> None:
    """Verify BankDisburseRequest and BankDisburseResponse contracts."""
    req = BankDisburseRequest(
        idempotency_key="idemp-xyz-999",
        amount_cents=250000,
        currency="USD",
        beneficiary_account_mask="******5555",
        routing_number="121000358",
        swift_bic="BOFAUS3NXXX",
        disbursement_token="tok_disb_111",
    )
    assert req.amount_cents == 250000
    assert req.idempotency_key == "idemp-xyz-999"

    # Invalid amount cents
    with pytest.raises(ValidationError):
        BankDisburseRequest(
            idempotency_key="idemp-xyz-999",
            amount_cents=0,
            beneficiary_account_mask="******5555",
            routing_number="121000358",
            swift_bic="BOFAUS3NXXX",
            disbursement_token="tok_disb_111",
        )

    # Response instantiation
    now = datetime.now(timezone.utc)
    res = BankDisburseResponse(
        status="CONFIRMED",
        bank_reference_id="FED-WIRE-88319",
        idempotency_key="idemp-xyz-999",
        amount_cents=250000,
        currency="USD",
        settled_at=now,
    )
    assert res.status == "CONFIRMED"
    assert res.bank_reference_id == "FED-WIRE-88319"
    assert res.settled_at == now


def test_ledger_entry_and_audit_schemas() -> None:
    """Verify LedgerEntryCreate and WireAuditLogCreate schemas."""
    wire_id = uuid.uuid4()
    entry = LedgerEntryCreate(
        wire_id=wire_id,
        account_type="customer_cash",
        direction="DEBIT",
        amount_cents=10000,
    )
    assert entry.direction == "DEBIT"

    # Invalid direction
    with pytest.raises(ValidationError):
        LedgerEntryCreate(
            wire_id=wire_id,
            account_type="customer_cash",
            direction="INVALID",
            amount_cents=10000,
        )

    # Audit schema
    audit = WireAuditLogCreate(
        wire_id=wire_id,
        previous_status="processing",
        new_status="settled",
        worker_hostname="pod-1",
        redelivered=False,
        event_description="Settled successfully",
    )
    assert audit.new_status == "settled"
    assert audit.redelivered is False
