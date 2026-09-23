"""Unit and integration tests for SQLAlchemy ORM models, table constraints, and DB pooling."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as app_db
from app.config import get_settings
from app.db import (
    _create_engine_and_factory,
    close_db_engine,
    get_engine,
    get_session,
    get_session_factory,
    init_db,
)
from app.models import Account, IdempotencyRecord, LedgerEntry, ReconciliationReport


@pytest.mark.unit
async def test_account_creation_and_repr(db_session: AsyncSession) -> None:
    """Verify Account persistence, defaults, and string representation."""
    acc_id = uuid.uuid4()
    num = f"9999{uuid.uuid4().hex[:12]}"
    account = Account(
        account_id=acc_id,
        account_number=num,
        account_mask="******2222",
        account_type="operating",
        balance_cents=500000,  # $5,000.00
        currency="USD",
    )
    db_session.add(account)
    await db_session.commit()

    # Query back
    result = await db_session.execute(select(Account).where(Account.account_id == acc_id))
    fetched = result.scalar_one()

    assert fetched.account_number == num
    assert fetched.balance_cents == 500000
    assert fetched.currency == "USD"
    assert num in repr(fetched)


@pytest.mark.unit
async def test_account_negative_balance_constraint(db_session: AsyncSession) -> None:
    """Verify that an account cannot have a negative balance."""
    account = Account(
        account_number=f"9999{uuid.uuid4().hex[:12]}",
        account_mask="******3333",
        balance_cents=-100,
        currency="USD",
    )
    db_session.add(account)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.unit
async def test_account_invalid_type_constraint(db_session: AsyncSession) -> None:
    """Verify that an account cannot have an invalid account_type."""
    account = Account(
        account_number=f"9999{uuid.uuid4().hex[:12]}",
        account_mask="******4444",
        account_type="invalid_type",
        balance_cents=1000,
    )
    db_session.add(account)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.unit
async def test_ledger_entry_creation_and_relationship(db_session: AsyncSession) -> None:
    """Verify LedgerEntry persistence, relationship to Account, and repr."""
    num = f"9999{uuid.uuid4().hex[:12]}"
    account = Account(
        account_number=num,
        account_mask="******5555",
        balance_cents=1000000,
    )
    db_session.add(account)
    await db_session.flush()

    today = date(2026, 9, 23)
    entry = LedgerEntry(
        account_id=account.account_id,
        amount_cents=150000,
        direction="credit",
        status="posted",
        period_date=today,
        description="Daily ACH Settlement Inflow",
    )
    db_session.add(entry)
    await db_session.commit()

    # Query back
    result = await db_session.execute(select(LedgerEntry).where(LedgerEntry.entry_id == entry.entry_id))
    fetched = result.scalar_one()

    assert fetched.amount_cents == 150000
    assert fetched.direction == "credit"
    assert fetched.period_date == today
    assert fetched.account.account_number == num
    assert "2026-09-23" in repr(fetched)


@pytest.mark.unit
async def test_ledger_entry_check_constraints(db_session: AsyncSession) -> None:
    """Verify LedgerEntry amount and direction check constraints."""
    account = Account(
        account_number=f"9999{uuid.uuid4().hex[:12]}",
        account_mask="******6666",
        balance_cents=1000000,
    )
    db_session.add(account)
    await db_session.flush()

    # 1. Non-positive amount
    entry_invalid_amount = LedgerEntry(
        account_id=account.account_id,
        amount_cents=0,
        direction="credit",
        period_date=date(2026, 9, 23),
    )
    db_session.add(entry_invalid_amount)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 2. Invalid direction
    entry_invalid_dir = LedgerEntry(
        account_id=account.account_id,
        amount_cents=100,
        direction="invalid",
        period_date=date(2026, 9, 23),
    )
    db_session.add(entry_invalid_dir)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.unit
async def test_reconciliation_report_uniqueness_and_constraints(db_session: AsyncSession) -> None:
    """Verify ReconciliationReport persistence, UNIQUE(period_date), and check constraints."""
    period = date(2026, 9, 23)
    report1 = ReconciliationReport(
        period_date=period,
        total_credits_cents=250000,
        total_debits_cents=250000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="sha256_mock_hash_abc123",
        metadata_json={"reconciled_by": "system"},
    )
    db_session.add(report1)
    await db_session.commit()

    # 1. Check repr
    assert "2026-09-23" in repr(report1)
    assert "balanced" in repr(report1)

    # 2. Duplicate period_date must raise IntegrityError
    report2 = ReconciliationReport(
        period_date=period,
        total_credits_cents=1000,
        total_debits_cents=1000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
    )
    db_session.add(report2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.unit
async def test_idempotency_record_lifecycle(db_session: AsyncSession) -> None:
    """Verify IdempotencyRecord persistence and repr."""
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    record = IdempotencyRecord(
        key="idemp_key_123456789",
        scope="reconciliation",
        expires_at=expires,
    )
    db_session.add(record)
    await db_session.commit()

    result = await db_session.execute(select(IdempotencyRecord).where(IdempotencyRecord.key == "idemp_key_123456789"))
    fetched = result.scalar_one()

    assert fetched.scope == "reconciliation"
    assert "idemp_key_123456789" in repr(fetched)


@pytest.mark.unit
async def test_db_pool_lifecycle_and_helpers() -> None:
    """Verify engine and session factory getters, worker role init, and cleanup."""
    # Test worker role re-init
    init_db(is_worker=True)
    engine = get_engine()
    factory = get_session_factory()
    assert engine is not None
    assert factory is not None

    # Test get_session generator happy path
    session_gen = get_session()
    session = await anext(session_gen)
    assert isinstance(session, AsyncSession)
    await session_gen.aclose()

    # Test get_session exception path
    error_gen = get_session()
    await anext(error_gen)
    with pytest.raises(RuntimeError):
        await error_gen.athrow(RuntimeError("Simulated error in session"))

    # Test lazy initialization if _engine or _session_factory is None
    app_db._engine = None
    app_db._session_factory = None
    engine_lazy = get_engine()
    assert engine_lazy is not None

    app_db._session_factory = None
    factory_lazy = get_session_factory()
    assert factory_lazy is not None

    # Test production environment pooling for both API and Worker
    settings = get_settings()
    original_env = settings.environment
    try:
        settings.environment = "production"
        prod_engine_api, _ = _create_engine_and_factory(is_worker=False)
        assert prod_engine_api is not None
        await prod_engine_api.dispose()

        prod_engine_worker, _ = _create_engine_and_factory(is_worker=True)
        assert prod_engine_worker is not None
        await prod_engine_worker.dispose()
    finally:
        settings.environment = original_env

    # Test close_db_engine
    await close_db_engine()
    # Re-init for other tests
    init_db(is_worker=False)
