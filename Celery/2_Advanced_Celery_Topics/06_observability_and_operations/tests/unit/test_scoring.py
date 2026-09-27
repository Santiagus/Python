"""Unit tests for heuristic fraud scoring and velocity evaluation (TC-03, TC-04)."""

from services.worker.tasks.scoring import calculate_risk_score, evaluate_screening


def test_calculate_risk_score_low_risk() -> None:
    """TC-03: Small transaction with low velocity produces 0 risk score and approval."""
    score, reasons = calculate_risk_score(
        amount_cents=10000,
        velocity_5m_count=0,
        client_ip="192.168.1.100",
    )
    assert score == 0
    assert reasons == []


def test_calculate_risk_score_standard_tier() -> None:
    """TC-03: Verify standard amount ($2,500) and minor velocity (2) produces expected points."""
    score, reasons = calculate_risk_score(
        amount_cents=250000,
        velocity_5m_count=2,
        client_ip="10.0.0.1",
    )
    assert score == 20
    assert "standard_value_transaction" in reasons
    assert "elevated_velocity" in reasons


def test_calculate_risk_score_medium_high_tier() -> None:
    """TC-03: Medium-high amount ($10,000) and velocity (5) triggers flagged_review."""
    score, reasons = calculate_risk_score(
        amount_cents=1000000,
        velocity_5m_count=5,
        client_ip="10.0.0.1",
    )
    assert score == 50
    assert "medium_high_value_transaction" in reasons
    assert "high_velocity_spike" in reasons


def test_calculate_risk_score_high_risk_and_bounding() -> None:
    """TC-04: Verify high value, velocity burst, and suspicious IP triggers score cap at 100."""
    score, reasons = calculate_risk_score(
        amount_cents=6000000,
        velocity_5m_count=12,
        client_ip="203.0.113.55",
    )
    assert score == 100
    assert "high_value_transaction" in reasons
    assert "extreme_velocity_burst" in reasons
    assert "suspicious_ip_range" in reasons


def test_calculate_risk_score_alternate_suspicious_ip() -> None:
    """TC-04: Verify alternate suspicious IP prefix triggers point addition."""
    score, reasons = calculate_risk_score(
        amount_cents=5000,
        velocity_5m_count=0,
        client_ip="198.51.100.99",
    )
    assert score == 30
    assert "suspicious_ip_range" in reasons


def test_evaluate_screening_task_approved() -> None:
    """TC-03: Verify evaluate_screening task produces 'approved' decision envelope."""
    payload_data = {
        "screening_id": "11223344-5566-7788-99aa-bbccddeeff00",
        "transaction_id": "tx_unit_001",
        "account_id": "acc_001",
        "entity_name": "Standard Company",
        "amount": "150.00",
        "currency": "USD",
        "client_ip": "172.16.0.5",
        "velocity_5m_count": 0,
    }

    result = evaluate_screening.apply(args=[payload_data]).result
    assert result["status"] == "ok"
    assert result["screening_id"] == "11223344-5566-7788-99aa-bbccddeeff00"
    assert result["risk_score"] == 0
    assert result["decision"] == "approved"


def test_evaluate_screening_task_flagged_review() -> None:
    """TC-03: Verify evaluate_screening task produces 'flagged_review' decision envelope."""
    payload_data = {
        "screening_id": "11223344-5566-7788-99aa-bbccddeeff00",
        "transaction_id": "tx_unit_002",
        "account_id": "acc_002",
        "entity_name": "Medium Corp",
        "amount": "12000.00",
        "currency": "USD",
        "client_ip": "172.16.0.5",
        "velocity_5m_count": 6,
    }

    result = evaluate_screening.apply(args=[payload_data]).result
    assert result["status"] == "ok"
    assert result["risk_score"] == 50
    assert result["decision"] == "flagged_review"


def test_evaluate_screening_task_blocked() -> None:
    """TC-04: Verify evaluate_screening task produces 'blocked' decision envelope."""
    payload_data = {
        "screening_id": "11223344-5566-7788-99aa-bbccddeeff00",
        "transaction_id": "tx_unit_003",
        "account_id": "acc_003",
        "entity_name": "High Risk Corp",
        "amount": "60000.00",
        "currency": "USD",
        "client_ip": "203.0.113.9",
        "velocity_5m_count": 3,
    }

    result = evaluate_screening.apply(args=[payload_data]).result
    assert result["status"] == "ok"
    assert result["risk_score"] == 90
    assert result["decision"] == "blocked"
