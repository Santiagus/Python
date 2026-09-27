"""Deep AML sanctions screening task and fatal error errback compensation.

Communicates with the Sanctions Watchlist Simulator API using persistent keep-alive
connection pooling and enforces the Result Envelope pattern during external outages.
"""

import logging
import os
from typing import Any

import httpx
from celery import Task

from services.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_HTTP_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=50,
    keepalive_expiry=30.0,
)
_SANCTIONS_API_URL = os.getenv("SANCTIONS_API_URL", "http://localhost:8015")
_shared_client = httpx.Client(
    base_url=_SANCTIONS_API_URL,
    limits=_HTTP_LIMITS,
    timeout=2.0,
)


def get_shared_client() -> httpx.Client:
    """Return the process-level persistent HTTP keepalive client.

    Returns:
        httpx.Client: Shared singleton HTTP client.
    """
    return _shared_client


@celery_app.task(
    name="services.worker.tasks.screening.check_aml_watchlist",
    bind=True,
    max_retries=2,
    default_retry_delay=2,
)
def check_aml_watchlist(
    self: Task,
    screening_id: str,
    entity_name: str,
    upstream_score: int = 0,
) -> dict[str, Any]:
    """Screen an individual or business entity against OFAC and AML watchlists.

    Args:
        self: Bound Celery task instance.
        screening_id: Unique UUID string identifying this screening ledger entry.
        entity_name: Legal counterparty entity name to verify.
        upstream_score: Heuristic risk points calculated by the upstream scoring task.

    Returns:
        dict[str, Any]: Standardized result envelope with status 'ok' or 'degraded'.
    """
    client = get_shared_client()

    logger.info(
        "aml_screening_task_started",
        extra={
            "task_id": self.request.id,
            "screening_id": screening_id,
            "entity_name": entity_name,
        },
    )

    try:
        response = client.post(
            "/api/v1/watchlists/check",
            json={"entity_name": entity_name},
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning(
            "aml_sanctions_api_degraded",
            extra={
                "screening_id": screening_id,
                "error_type": type(exc).__name__,
                "detail": str(exc),
            },
        )
        return {
            "status": "degraded",
            "screening_id": screening_id,
            "is_sanctioned": False,
            "matches": [],
            "decision": "flagged_review",
            "fallback_score": 40,
            "reasons": ["aml_watchlist_timeout"],
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    matches = data.get("matches", [])
    is_sanctioned = bool(data.get("is_sanctioned", False))

    if is_sanctioned and matches:
        max_confidence = max(m.get("match_confidence", 0.0) for m in matches)
        decision = "blocked" if max_confidence >= 98.0 else "flagged_review"
        composite_score = max(upstream_score, 95)
        reasons = ["sanctions_watchlist_positive_match"]
    else:
        decision = "approved" if upstream_score < 50 else "flagged_review"
        composite_score = upstream_score
        reasons = []

    return {
        "status": "ok",
        "screening_id": screening_id,
        "is_sanctioned": is_sanctioned,
        "matches": matches,
        "decision": decision,
        "risk_score": composite_score,
        "reasons": reasons,
        "errors": [],
    }


@celery_app.task(
    name="services.worker.tasks.screening.handle_screening_failure",
    bind=True,
)
def handle_screening_failure(
    self: Task,
    request: Any,
    exc: Any,
    traceback: Any,
    screening_id: str,
) -> dict[str, Any]:
    """Celery errback compensation handler linked via link_error.

    Args:
        self: Bound Celery task context.
        request: Request context of the failed upstream task.
        exc: Exception raised by upstream task.
        traceback: Serialized traceback string.
        screening_id: Identifier of the affected screening ledger row.

    Returns:
        dict[str, Any]: Failure audit payload.
    """
    error_msg = str(exc) if exc else "unknown_fatal_error"
    logger.error(
        "screening_errback_triggered",
        extra={
            "task_id": self.request.id,
            "screening_id": screening_id,
            "error": error_msg,
        },
    )

    return {
        "status": "failed",
        "screening_id": screening_id,
        "error": error_msg,
        "decision": "failed",
        "decision_reason": "fatal_worker_error",
    }
