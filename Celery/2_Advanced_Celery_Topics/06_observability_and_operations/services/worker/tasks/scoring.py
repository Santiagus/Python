"""Real-time transaction velocity and heuristic fraud scoring task.

Evaluates transaction amounts, velocity spikes, and network IP reputation
using minor-unit financial arithmetic and pure integer math.
"""

import logging
from typing import Any

from celery import Task

from services.worker.celery_app import celery_app
from services.worker.schemas import ScreeningPayload

logger = logging.getLogger(__name__)


def calculate_risk_score(
    amount_cents: int,
    velocity_5m_count: int,
    client_ip: str,
) -> tuple[int, list[str]]:
    """Compute heuristic fraud score bounded between 0 and 100.

    Args:
        amount_cents: Transaction magnitude in minor-unit integer cents.
        velocity_5m_count: Number of recent transactions by this customer.
        client_ip: Originating client IP address.

    Returns:
        tuple[int, list[str]]: Composite risk score and list of diagnostic triggers.
    """
    points = 0
    reasons: list[str] = []

    # 1. Evaluate transaction monetary threshold
    if amount_cents >= 5000000:  # >= $50,000.00
        points += 50
        reasons.append("high_value_transaction")
    elif amount_cents >= 1000000:  # >= $10,000.00
        points += 25
        reasons.append("medium_high_value_transaction")
    elif amount_cents >= 250000:  # >= $2,500.00
        points += 10
        reasons.append("standard_value_transaction")

    # 2. Evaluate rolling velocity burst
    if velocity_5m_count >= 10:
        points += 40
        reasons.append("extreme_velocity_burst")
    elif velocity_5m_count >= 5:
        points += 25
        reasons.append("high_velocity_spike")
    elif velocity_5m_count >= 2:
        points += 10
        reasons.append("elevated_velocity")

    # 3. Evaluate client IP reputation
    if client_ip.startswith("203.0.113.") or client_ip.startswith("198.51.100.99"):
        points += 30
        reasons.append("suspicious_ip_range")

    # 4. Strict bounding invariant in range [0, 100]
    final_score = min(max(points, 0), 100)
    return final_score, reasons


@celery_app.task(
    name="services.worker.tasks.scoring.evaluate_screening",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def evaluate_screening(self: Task, payload_data: dict[str, Any]) -> dict[str, Any]:
    """Execute real-time heuristic scoring and velocity assessment.

    Args:
        self: Bound Celery task context.
        payload_data: Normalized dictionary matching ScreeningPayload schema.

    Returns:
        dict[str, Any]: Result envelope containing risk score and triage decision.
    """
    payload = ScreeningPayload.model_validate(payload_data)

    logger.info(
        "scoring_task_started",
        extra={
            "task_id": self.request.id,
            "screening_id": payload.screening_id,
            "transaction_id": payload.transaction_id,
        },
    )

    score, reasons = calculate_risk_score(
        amount_cents=payload.amount_cents,
        velocity_5m_count=payload.velocity_5m_count,
        client_ip=payload.client_ip,
    )

    if score >= 85:
        decision = "blocked"
    elif score >= 50:
        decision = "flagged_review"
    else:
        decision = "approved"

    return {
        "status": "ok",
        "screening_id": payload.screening_id,
        "transaction_id": payload.transaction_id,
        "account_id": payload.account_id,
        "entity_name": payload.entity_name,
        "risk_score": score,
        "decision": decision,
        "reasons": reasons,
    }
