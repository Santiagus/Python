"""Unit tests for Pydantic v2 schemas and monetary precision calculations."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    AccountResponse,
    BatchDisbursementRequest,
    BatchDisbursementResponse,
    BatchStatus,
    DisbursementItem,
    DLQRedriveRequest,
    DLQRedriveResponse,
    HealthResponse,
    InstantPaymentRequest,
    InstantPaymentResponse,
    PaymentPriority,
    PaymentRail,
    PaymentStatus,
    QueueMetric,
    QueueMetricsResponse,
    from_cents,
    to_cents,
)


@pytest.mark.unit
class TestMonetaryPrecision:
    """Test minor-unit integer cents conversion and round-half-up math."""

    def test_to_cents_exact(self) -> None:
        """Verify accurate integer cent conversion."""
        assert to_cents(Decimal("0.01")) == 1
        assert to_cents(Decimal("1.00")) == 100
        assert to_cents(Decimal("12.34")) == 1234
        assert to_cents(Decimal("1000000.50")) == 100000050

    def test_to_cents_round_half_up(self) -> None:
        """Verify standard banking ROUND_HALF_UP rounding."""
        assert to_cents(Decimal("10.005")) == 1001
        assert to_cents(Decimal("10.004")) == 1000
        assert to_cents(Decimal("0.005")) == 1

    def test_from_cents_exact(self) -> None:
        """Verify integer cent to major Decimal conversion."""
        assert from_cents(1) == Decimal("0.01")
        assert from_cents(100) == Decimal("1.00")
        assert from_cents(1234) == Decimal("12.34")
        assert from_cents(0) == Decimal("0.00")


@pytest.mark.unit
class TestInstantPaymentSchemas:
    """Test validation constraints on instant payout request and response schemas."""

    def test_valid_instant_payment_request(self) -> None:
        """Valid FedNow and RTP payloads must instantiate cleanly."""
        req = InstantPaymentRequest(
            idempotency_key="idemp_unit_test_001",
            source_account_id=uuid4(),
            destination_account_number="9876543210",
            destination_routing_number="021000021",
            amount=Decimal("150.00"),
            rail=PaymentRail.rtp,
            description="Testing payout",
        )
        assert req.rail == PaymentRail.rtp
        assert req.amount == Decimal("150.00")

    def test_invalid_rail_rejected(self) -> None:
        """Instant payouts cannot use ACH rail."""
        with pytest.raises(ValidationError) as exc:
            InstantPaymentRequest(
                idempotency_key="idemp_unit_test_002",
                source_account_id=uuid4(),
                destination_account_number="9876543210",
                destination_routing_number="021000021",
                amount=Decimal("150.00"),
                rail=PaymentRail.ach,  # ACH not permitted on instant route
            )
        assert "Instant payments must use 'fednow' or 'rtp'" in str(exc.value)

    def test_invalid_routing_number(self) -> None:
        """Routing number must be exactly 9 digits."""
        with pytest.raises(ValidationError):
            InstantPaymentRequest(
                idempotency_key="idemp_unit_test_003",
                source_account_id=uuid4(),
                destination_account_number="9876543210",
                destination_routing_number="1234",  # Too short
                amount=Decimal("150.00"),
            )

    def test_negative_or_zero_amount_rejected(self) -> None:
        """Amount must be strictly greater than zero."""
        with pytest.raises(ValidationError):
            InstantPaymentRequest(
                idempotency_key="idemp_unit_test_004",
                source_account_id=uuid4(),
                destination_account_number="9876543210",
                destination_routing_number="021000021",
                amount=Decimal("0.00"),
            )

        with pytest.raises(ValidationError):
            InstantPaymentRequest(
                idempotency_key="idemp_unit_test_005",
                source_account_id=uuid4(),
                destination_account_number="9876543210",
                destination_routing_number="021000021",
                amount=Decimal("-10.00"),
            )

    def test_instant_payment_response_serialization(self) -> None:
        """Verify InstantPaymentResponse serialization."""
        now = datetime.now(timezone.utc)
        pid = uuid4()
        aid = uuid4()
        resp = InstantPaymentResponse(
            payment_id=pid,
            idempotency_key="idemp_resp_001",
            source_account_id=aid,
            destination_account_mask="******1098",
            destination_routing_number="021000021",
            amount=Decimal("250.00"),
            amount_cents=25000,
            rail=PaymentRail.fednow,
            priority=PaymentPriority.critical,
            status=PaymentStatus.settled,
            created_at=now,
            cleared_at=now,
            external_reference="CLR_FEDNOW_123",
            error_detail=None,
        )
        assert resp.payment_id == pid
        assert resp.status == PaymentStatus.settled


@pytest.mark.unit
class TestBatchDisbursementSchemas:
    """Test validation constraints on batch disbursement schemas."""

    def test_valid_batch_request(self) -> None:
        """Valid batch request with multiple items."""
        req = BatchDisbursementRequest(
            file_reference="batch_file_001",
            source_account_id=uuid4(),
            disbursements=[
                DisbursementItem(
                    recipient_name="Alice",
                    account_number="12345678",
                    routing_number="021000021",
                    amount=Decimal("500.00"),
                ),
                DisbursementItem(
                    recipient_name="Bob",
                    account_number="87654321",
                    routing_number="021000021",
                    amount=Decimal("750.50"),
                ),
            ],
        )
        assert len(req.disbursements) == 2
        assert req.file_reference == "batch_file_001"

    def test_empty_disbursements_list_rejected(self) -> None:
        """Batch must contain at least 1 item."""
        with pytest.raises(ValidationError):
            BatchDisbursementRequest(
                file_reference="batch_empty",
                source_account_id=uuid4(),
                disbursements=[],
            )

    def test_disbursement_item_invalid_fields(self) -> None:
        """Disbursement line items validate routing and positive amounts."""
        with pytest.raises(ValidationError):
            DisbursementItem(
                recipient_name="X",  # Too short (min 2)
                account_number="12345678",
                routing_number="021000021",
                amount=Decimal("100.00"),
            )


@pytest.mark.unit
class TestOperationalSchemas:
    """Test queue metrics, health, and redrive schemas."""

    def test_queue_metrics_schemas(self) -> None:
        """Verify QueueMetric and QueueMetricsResponse models."""
        metric = QueueMetric(
            name="critical",
            messages_ready=5,
            messages_unacknowledged=1,
            consumers=4,
        )
        assert metric.messages_ready == 5
        resp = QueueMetricsResponse(queues=[metric], total_ready=5)
        assert resp.total_ready == 5

    def test_dlq_redrive_schemas(self) -> None:
        """Verify DLQRedriveRequest and Response."""
        req = DLQRedriveRequest(source_queue="rejected_payments", destination_queue="critical", max_messages=50)
        assert req.max_messages == 50
        resp = DLQRedriveResponse(messages_redriven=10, source_queue="rejected_payments", destination_queue="critical")
        assert resp.messages_redriven == 10

    def test_health_response_schema(self) -> None:
        """Verify HealthResponse schema."""
        h = HealthResponse(status="healthy", environment="test", database="connected", rabbitmq="connected", redis="connected")
        assert h.status == "healthy"

    def test_account_response_schema(self) -> None:
        """Verify AccountResponse schema."""
        acc_id = uuid4()
        acc = AccountResponse(account_id=acc_id, account_number_mask="******5501", balance=Decimal("100.00"), balance_cents=10000, currency="USD")
        assert acc.balance_cents == 10000

