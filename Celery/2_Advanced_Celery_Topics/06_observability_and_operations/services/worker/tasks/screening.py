"""Deep AML sanctions screening task and fatal error errback compensation.

Communicates with the Sanctions Watchlist Simulator API using persistent keep-alive
connection pooling and enforces the Result Envelope pattern during external outages.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from celery import Task
from sqlalchemy import update

from app.database import session_factory
from app.models import ScreeningModel, WatchlistHitModel
from services.worker.celery_app import celery_app
from services.worker.tasks.utils import run_sync

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


async def _async_persist_screening(
    screening_id: str,
    status: str,
    risk_score: int,
    decision_reason: str,
    matches: list[dict[str, Any]] | None = None,
) -> None:
    """Persist screening state machine transition and watchlist hits asynchronously.

    Args:
        screening_id: Persistent UUID string of the screening ledger record.
        status: Target state machine status (e.g., approved, flagged_review, blocked).
        risk_score: Final composite fraud risk score.
        decision_reason: Diagnostic reason explaining triage outcome.
        matches: Optional list of matched compliance records.
    """
    # 1. Validate screening UUID format
    try:
        screening_uuid = UUID(screening_id)
    except (ValueError, TypeError):
        logger.error("invalid_screening_uuid_format", extra={"screening_id": screening_id})
        return

    # 2. Update master screening record and insert watchlist hit evidence
    async with session_factory() as session:
        stmt = (
            update(ScreeningModel)
            .where(ScreeningModel.id == screening_uuid)
            .values(
                status=status,
                risk_score=risk_score,
                decision_reason=decision_reason,
            )
        )
        await session.execute(stmt)

        if matches:
            for match in matches:
                hit = WatchlistHitModel(
                    screening_id=screening_uuid,
                    entity_name=match.get("entity_name", ""),
                    watchlist_type=match.get("watchlist_type", "OFAC_SDN"),
                    match_confidence=Decimal(str(match.get("match_confidence", 0.0))),
                )
                session.add(hit)

        await session.commit()
        logger.info(
            "screening_state_transition_persisted",
            extra={
                "screening_id": screening_id,
                "status": status,
                "risk_score": risk_score,
            },
        )


def _persist_screening(
    screening_id: str,
    status: str,
    risk_score: int,
    decision_reason: str,
    matches: list[dict[str, Any]] | None = None,
) -> None:
    """Synchronous worker wrapper bridging Celery worker process to async persistence.

    Args:
        screening_id: UUID string of the screening record.
        status: Target state machine status.
        risk_score: Final composite risk score.
        decision_reason: Diagnostic reason.
        matches: Optional list of sanctions matches.
    """
    coro = _async_persist_screening(
        screening_id=screening_id,
        status=status,
        risk_score=risk_score,
        decision_reason=decision_reason,
        matches=matches,
    )
    try:
        run_sync(coro)
    except Exception as exc:
        coro.close()
        logger.error(
            "screening_persistence_failed",
            extra={"screening_id": screening_id, "error": str(exc)},
        )


async def _async_persist_failure(screening_id: str, error_msg: str) -> None:
    """Persist fatal errback failure transition to PostgreSQL asynchronously.

    Args:
        screening_id: UUID string of the screening record.
        error_msg: Error message or traceback summary.
    """
    try:
        screening_uuid = UUID(screening_id)
    except (ValueError, TypeError):
        logger.error("invalid_screening_uuid_format", extra={"screening_id": screening_id})
        return

    async with session_factory() as session:
        stmt = (
            update(ScreeningModel)
            .where(ScreeningModel.id == screening_uuid)
            .values(
                status="failed",
                decision_reason=f"fatal_worker_error: {error_msg[:200]}",
            )
        )
        await session.execute(stmt)
        await session.commit()
        logger.info("screening_failure_transition_persisted", extra={"screening_id": screening_id})


def _persist_failure(screening_id: str, error_msg: str) -> None:
    """Synchronous worker wrapper to persist fatal failure state in errback.

    Args:
        screening_id: UUID string of the screening record.
        error_msg: Error message to record.
    """
    coro = _async_persist_failure(screening_id, error_msg)
    try:
        run_sync(coro)
    except Exception as exc:
        coro.close()
        logger.error(
            "failure_persistence_failed",
            extra={"screening_id": screening_id, "error": str(exc)},
        )


@celery_app.task(
    name="services.worker.tasks.screening.check_aml_watchlist",
    bind=True,
    max_retries=2,
    default_retry_delay=2,
)
def check_aml_watchlist(
    self: Task,
    screening_id_or_data: str | dict[str, Any],
    entity_name: str | None = None,
    upstream_score: int = 0,
) -> dict[str, Any]:
    """Screen an individual or business entity against OFAC and AML watchlists.

    Args:
        self: Bound Celery task instance.
        screening_id_or_data: UUID string or upstream scoring result envelope dictionary.
        entity_name: Legal counterparty entity name to verify.
        upstream_score: Heuristic risk points calculated by the upstream scoring task.

    Returns:
        dict[str, Any]: Standardized result envelope with status 'ok' or 'degraded'.
    """
    # 1. Unpack upstream chain argument or direct task parameters
    if isinstance(screening_id_or_data, dict):
        screening_id = str(screening_id_or_data.get("screening_id", ""))
        entity_name = str(screening_id_or_data.get("entity_name", entity_name or ""))
        upstream_score = int(screening_id_or_data.get("risk_score", upstream_score))
    else:
        screening_id = str(screening_id_or_data)
        entity_name = str(entity_name or "")

    client = get_shared_client()

    logger.info(
        "aml_screening_task_started",
        extra={
            "task_id": self.request.id,
            "screening_id": screening_id,
            "entity_name": entity_name,
        },
    )

    # 2. Invoke Sanctions Watchlist Simulator API with Result Envelope degradation
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
        _persist_screening(
            screening_id=screening_id,
            status="flagged_review",
            risk_score=40,
            decision_reason="aml_watchlist_timeout",
            matches=[],
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

    # 3. Evaluate sanctions match confidence thresholds
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

    # 4. Persist terminal decision and watchlist evidence to database
    _persist_screening(
        screening_id=screening_id,
        status=decision,
        risk_score=composite_score,
        decision_reason=", ".join(reasons) if reasons else "automated_evaluation_completed",
        matches=matches,
    )

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
    *args: Any,
    screening_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Celery errback compensation handler linked via link_error.

    Args:
        self: Bound Celery task context.
        *args: Variable arguments passed by Celery error propagation.
        screening_id: Optional keyword identifier of the affected screening ledger row.
        **kwargs: Additional keyword arguments from Celery caller.

    Returns:
        dict[str, Any]: Failure audit payload.
    """
    # 1. Resolve screening_id across kwargs, direct keyword, or positional args
    resolved_id = screening_id or kwargs.get("screening_id")
    if not resolved_id:
        for arg in args:
            if isinstance(arg, str) and len(arg) == 36 and "-" in arg:
                resolved_id = arg
                break
    resolved_id = str(resolved_id or "")

    # 2. Extract exception from kwargs or positional args
    exc = kwargs.get("exc")
    if not exc:
        for arg in args:
            if isinstance(arg, Exception):
                exc = arg
                break

    error_msg = str(exc) if exc else "unknown_fatal_error"
    logger.error(
        "screening_errback_triggered",
        extra={
            "task_id": self.request.id,
            "screening_id": resolved_id,
            "error": error_msg,
        },
    )

    # 3. Persist terminal failure transition in database
    if resolved_id:
        _persist_failure(resolved_id, error_msg)

    return {
        "status": "failed",
        "screening_id": resolved_id,
        "error": error_msg,
        "decision": "failed",
        "decision_reason": "fatal_worker_error",
    }
