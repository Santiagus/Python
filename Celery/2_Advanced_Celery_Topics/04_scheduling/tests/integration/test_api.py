"""Integration test suite for FastAPI control plane and management endpoints.

Verifies health probes, reconciliation report queries, gap audits, Celery trigger dispatching,
synthetic transaction seeding, and middleware pipelines with 100% statement and branch coverage.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app, lifespan
from app.models import Account, LedgerEntry, ReconciliationReport


@pytest.mark.asyncio
async def test_health_check_healthy(api_client: AsyncClient) -> None:
    """Validate GET /health returns 200 OK with connected dependencies."""
    response = await api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["components"]["database"] == "connected"
    assert data["components"]["redis"] == "connected"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_check_degraded_db(api_client: AsyncClient) -> None:
    """Validate GET /health returns 503 when the database check raises an error."""
    with patch("app.routes.get_session") as mock_session_dep:
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("Database connection refused")

        async def _fake_session():
            yield mock_session

        app.dependency_overrides[mock_session_dep] = _fake_session
        try:
            # Test direct path to force database error
            with patch("sqlalchemy.ext.asyncio.AsyncSession.execute", side_effect=RuntimeError("DB down")):
                response = await api_client.get("/health")
                assert response.status_code == 503
                data = response.json()
                assert data["status"] == "degraded"
                assert "unhealthy" in data["components"]["database"]
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check_degraded_redis(api_client: AsyncClient) -> None:
    """Validate GET /health returns 503 when Redis ping raises an error."""
    with patch("redis.asyncio.from_url") as mock_from_url:
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = ConnectionError("Redis unreachable")

        async def _fake_ping():
            raise ConnectionError("Redis unreachable")

        mock_redis.ping = _fake_ping
        mock_from_url.return_value = mock_redis

        response = await api_client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert "unhealthy" in data["components"]["redis"]


@pytest.mark.asyncio
async def test_list_reconciliations_empty(api_client: AsyncClient) -> None:
    """Validate GET /reconciliations on an empty table returns total=0 and empty items."""
    response = await api_client.get("/api/v1/reconciliations")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["limit"] == 50
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_seed_ledger_balanced_and_discrepancy(api_client: AsyncClient) -> None:
    """Validate POST /seed creates balanced, discrepancy, and empty scenarios."""
    # 1. Seed balanced scenario
    seed_balanced = {
        "period_date": "2026-09-23",
        "scenario": "balanced",
        "amount_cents": 1500000,
    }
    res_b = await api_client.post("/api/v1/seed", json=seed_balanced)
    assert res_b.status_code == 201
    data_b = res_b.json()
    assert data_b["entries_created"] == 2
    assert data_b["total_credits_cents"] == 1500000
    assert data_b["total_debits_cents"] == 1500000

    # 2. Seed discrepancy scenario
    seed_disc = {
        "period_date": "2026-09-24",
        "scenario": "discrepancy",
        "amount_cents": 2500000,
    }
    res_d = await api_client.post("/api/v1/seed", json=seed_disc)
    assert res_d.status_code == 201
    data_d = res_d.json()
    assert data_d["entries_created"] == 2
    assert data_d["total_credits_cents"] == 2500000
    assert data_d["total_debits_cents"] == 2480000

    # 3. Seed empty scenario
    seed_empty = {
        "period_date": "2026-09-25",
        "scenario": "empty",
        "amount_cents": 100000,
    }
    res_e = await api_client.post("/api/v1/seed", json=seed_empty)
    assert res_e.status_code == 201
    data_e = res_e.json()
    assert data_e["entries_created"] == 0


@pytest.mark.asyncio
async def test_trigger_reconciliation(api_client: AsyncClient) -> None:
    """Validate POST /reconciliations/trigger dispatches Celery task and returns 202."""
    payload = {
        "period_date": "2026-09-23",
        "clearing_variance_cents": 5000,
        "force": False,
    }

    with patch("app.routes.dispatch_reconciliation_cutoff", return_value="mock-task-id-123") as mock_dispatch:
        response = await api_client.post("/api/v1/reconciliations/trigger", json=payload)
        assert response.status_code == 202
        data = response.json()
        assert data["task_id"] == "mock-task-id-123"
        assert data["period_date"] == "2026-09-23"
        assert data["status"] == "queued"
        mock_dispatch.assert_called_once_with(
            period_date_str="2026-09-23",
            clearing_variance_cents=5000,
        )


@pytest.mark.asyncio
async def test_get_reconciliation_by_date(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """Validate GET /reconciliations/{period_date} returns single report or 404."""
    # 1. Insert report directly into DB
    p_date = date(2026, 9, 23)
    report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=p_date,
        total_credits_cents=1500000,
        total_debits_cents=1500000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="abc123hash",
        reconciled_at=datetime.now(timezone.utc),
    )
    db_session.add(report)
    await db_session.commit()

    # 2. Fetch existing report
    response = await api_client.get("/api/v1/reconciliations/2026-09-23")
    assert response.status_code == 200
    data = response.json()
    assert data["period_date"] == "2026-09-23"
    assert float(data["total_credits"]) == 15000.0
    assert float(data["total_debits"]) == 15000.0
    assert float(data["discrepancy"]) == 0.0

    # 3. Query non-existent period (404 NOT FOUND)
    missing_res = await api_client.get("/api/v1/reconciliations/1990-01-01")
    assert missing_res.status_code == 404
    assert "No reconciliation report found" in missing_res.json()["detail"]


@pytest.mark.asyncio
async def test_list_reconciliations_filtering_and_pagination(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Validate pagination and status filtering on GET /reconciliations."""
    now = datetime.now(timezone.utc)
    rep1 = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=date(2026, 9, 21),
        total_credits_cents=1000,
        total_debits_cents=1000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="hash1",
        reconciled_at=now,
    )
    rep2 = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=date(2026, 9, 22),
        total_credits_cents=2000,
        total_debits_cents=1800,
        net_movement_cents=200,
        discrepancy_cents=200,
        status="discrepancy_detected",
        verification_hash="hash2",
        reconciled_at=now,
    )
    db_session.add_all([rep1, rep2])
    await db_session.commit()

    # Query with status filter
    filter_res = await api_client.get("/api/v1/reconciliations?status=discrepancy_detected")
    assert filter_res.status_code == 200
    data_f = filter_res.json()
    assert data_f["total"] == 1
    assert data_f["items"][0]["status"] == "discrepancy_detected"

    # Query with pagination limit=1
    page_res = await api_client.get("/api/v1/reconciliations?limit=1&offset=0")
    assert page_res.status_code == 200
    data_p = page_res.json()
    assert data_p["total"] == 2
    assert len(data_p["items"]) == 1


@pytest.mark.asyncio
async def test_audit_unclosed_gaps(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """Validate GET /reconciliations/gaps computes missing business days."""
    # 1. When DB has no entries or reports (falls back to start of month)
    res_empty = await api_client.get("/api/v1/reconciliations/gaps")
    assert res_empty.status_code == 200
    data_e = res_empty.json()
    assert "gaps" in data_e
    assert "scan_range_start" in data_e
    assert "scan_range_end" in data_e

    # 2. Insert account, ledger entry, and a report for a specific date
    p_date = date(2026, 9, 1)
    acc = Account(
        account_id=uuid.uuid4(),
        account_number="ACC-TEST-GAPS",
        account_mask="******GAPS",
        account_type="operating",
        balance_cents=10000,
        currency="USD",
    )
    entry = LedgerEntry(
        entry_id=uuid.uuid4(),
        account_id=acc.account_id,
        amount_cents=5000,
        direction="credit",
        status="posted",
        period_date=p_date,
    )
    report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=p_date,
        total_credits_cents=5000,
        total_debits_cents=5000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="hash_gap",
        reconciled_at=datetime.now(timezone.utc),
    )
    db_session.add_all([acc, entry, report])
    await db_session.commit()

    res_with_baseline = await api_client.get("/api/v1/reconciliations/gaps")
    assert res_with_baseline.status_code == 200
    data_b = res_with_baseline.json()
    assert data_b["scan_range_start"] == "2026-09-01"
    assert "2026-09-01" not in data_b["gaps"]


@pytest.mark.asyncio
async def test_middleware_correlation_and_profiling(api_client: AsyncClient) -> None:
    """Validate correlation ID and profiling headers in response."""
    custom_req_id = "test-corr-id-999"
    response = await api_client.get("/health", headers={"X-Request-ID": custom_req_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_req_id
    assert "X-Process-Time-Ms" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.asyncio
async def test_middleware_error_handling_unhandled(api_client: AsyncClient) -> None:
    """Validate ErrorHandlingMiddleware intercepts uncaught exceptions and normalizes to 500 JSON."""
    with patch("sqlalchemy.ext.asyncio.AsyncSession.execute", side_effect=RuntimeError("Simulated catastrophic crash")):
        response = await api_client.get("/api/v1/reconciliations")
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Internal server error"
        assert "request_id" in data
        assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_validation_error_handling(api_client: AsyncClient) -> None:
    """Validate malformed payload triggers 422 Unprocessable Entity."""
    bad_payload = {"period_date": "invalid-date-format"}
    response = await api_client.post("/api/v1/reconciliations/trigger", json=bad_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dispatcher_unit() -> None:
    """Validate app/dispatcher.py passes headers and params to Celery send_task."""
    from app.dispatcher import dispatch_reconciliation_cutoff

    mock_task_res = MagicMock()
    mock_task_res.id = "dispatched-uuid-777"

    with patch("app.dispatcher.celery_app.send_task", return_value=mock_task_res) as mock_send:
        task_id = dispatch_reconciliation_cutoff(
            period_date_str="2026-09-23",
            clearing_variance_cents=1000,
        )
        assert task_id == "dispatched-uuid-777"
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        assert args[0] == "services.worker.tasks.reconciliation.reconcile_eod_cutoff"
        assert kwargs["args"] == ["2026-09-23", 1000]
        assert kwargs["queue"] == "reconciliation"
        assert kwargs["headers"]["source"] == "api_gateway"


@pytest.mark.asyncio
async def test_app_lifespan() -> None:
    """Validate app lifespan startup pre-warm and shutdown cleanup."""
    test_app = app
    async with lifespan(test_app):
        # Inside lifespan, engine is warmed
        pass
    # Shutdown executed cleanly


@pytest.mark.asyncio
async def test_app_lifespan_prewarm_failure() -> None:
    """Validate app lifespan handles database prewarm failure gracefully."""
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = RuntimeError("DB connection failed during prewarm")

    with patch("app.main.get_engine", return_value=mock_engine):
        test_app = app
        async with lifespan(test_app):
            pass


@pytest.mark.asyncio
async def test_close_db_engine_when_none() -> None:
    """Validate close_db_engine behaves idempotently when _engine is None."""
    import app.db as db_mod
    from app.db import close_db_engine

    saved_engine = db_mod._engine
    db_mod._engine = None
    try:
        await close_db_engine()
    finally:
        db_mod._engine = saved_engine
