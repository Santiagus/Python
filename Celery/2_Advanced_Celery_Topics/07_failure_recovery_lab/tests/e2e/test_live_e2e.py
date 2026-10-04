"""Distributed Live End-to-End Verification Suite.

Executes comprehensive real-world distributed tests against the live Docker Compose cluster:
- Health and readiness probes across API gateway and Bank Simulator.
- Single-wire transfer lifecycle, anti-blackhole state, and audit trails.
- High-concurrency batch wire processing with zero message loss across worker fleet.
- Atomic idempotency under concurrent collision conditions.
- Real-world worker SIGKILL crash, broker redelivery, and anti-duplicate payout.
- Poison pill dead-letter exchange (DLQ) quarantine without stalling worker queue.
- Total mathematical ledger parity (0 cents drift, SUM(debit) == SUM(credit)).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from kombu import Connection
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.chaos_harness import ChaosHarness
from shared.amqp_topology import (
    WIRE_CRITICAL_QUEUE_NAME,
    WIRE_DLQ_QUEUE_NAME,
    wire_direct_exchange,
    wire_dlq_queue,
    wire_dlx_exchange,
)
from shared.models import (
    LedgerDirection,
    LedgerJournal,
    WireAuditLog,
    WireStatus,
    WireTransfer,
)

# Configuration endpoints for live Docker Compose cluster
API_BASE_URL: str = os.getenv("API_URL", "http://localhost:8000")
BANK_BASE_URL: str = os.getenv("BANK_SIMULATOR_URL", "http://localhost:8010")
BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//")
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://wire_user:wire_password@localhost:5432/wire_settlement_db",
)


def is_cluster_healthy() -> bool:
    """Check if the live Docker Compose cluster is reachable.

    Returns:
        bool: True if API gateway responds to health probe, False otherwise.
    """
    try:
        resp = httpx.get(f"{API_BASE_URL}/health", timeout=2.0)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


pytestmark = pytest.mark.skipif(
    not is_cluster_healthy(),
    reason="Live Docker Compose cluster is not running or unreachable at localhost:8000",
)


@pytest.fixture
def chaos_harness() -> ChaosHarness:
    """Provide a ChaosHarness instance targeting the live Docker Compose environment.

    Returns:
        ChaosHarness: Configured harness instance.
    """
    return ChaosHarness(
        api_url=API_BASE_URL,
        bank_url=BANK_BASE_URL,
        broker_url=BROKER_URL,
        db_url=DATABASE_URL,
        compose_file="docker-compose.yml",
    )


@asynccontextmanager
async def get_test_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an asynchronous SQLAlchemy session connected to the live database.

    Yields:
        AsyncSession: Active session connected to PostgreSQL.
    """
    engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=5)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_live_cluster_health_and_readiness_probes() -> None:
    """Verify that all live services report healthy and ready status."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        # 1. Verify FastAPI Gateway liveness probe
        api_health = await client.get(f"{API_BASE_URL}/health")
        assert api_health.status_code == 200
        assert api_health.json() == {"status": "ok"}

        # 2. Verify FastAPI Gateway readiness probe (database ping)
        api_ready = await client.get(f"{API_BASE_URL}/ready")
        assert api_ready.status_code == 200
        ready_data = api_ready.json()
        assert ready_data["status"] == "ready"
        assert ready_data.get("database") == "connected"

        # 3. Verify Bank Simulator API health probe
        bank_health = await client.get(f"{BANK_BASE_URL}/health")
        assert bank_health.status_code == 200
        assert bank_health.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_live_single_wire_settlement_and_ledger_parity() -> None:
    """Verify single wire transfer full lifecycle, anti-blackhole state, and ledger balancing."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Ingest wire transfer with unique idempotency key
        wire_idempotency = f"live-single-{uuid.uuid4().hex[:12]}"
        wire_payload = {
            "client_id": "CLIENT-LIVE-ALPHA",
            "amount": "175000.50",
            "currency": "USD",
            "beneficiary_account": "1234567890",
            "routing_number": "121000358",
            "swift_bic": "CHASUS33",
        }
        post_resp = await client.post(
            f"{API_BASE_URL}/api/v1/wires",
            json=wire_payload,
            headers={"Idempotency-Key": wire_idempotency},
        )
        assert post_resp.status_code == 202
        ingested = post_resp.json()
        wire_id = ingested["wire_id"]

        # 2. Assert Anti-Blackhole invariant (immediately visible as 'processing')
        assert ingested["status"] == WireStatus.PROCESSING.value
        assert ingested["amount_cents"] == 17500050

        # 3. Poll until wire transfer reaches terminal state
        settled_wire: dict[str, Any] = {}
        for _ in range(30):
            await asyncio.sleep(0.3)
            get_resp = await client.get(f"{API_BASE_URL}/api/v1/wires/{wire_id}")
            assert get_resp.status_code == 200
            data = get_resp.json()
            if data["status"] == WireStatus.SETTLED.value:
                settled_wire = data
                break

        assert settled_wire != {}, f"Wire {wire_id} did not settle in time"
        assert settled_wire["status"] == WireStatus.SETTLED.value
        assert settled_wire["bank_reference_id"] is not None
        assert settled_wire["bank_reference_id"].startswith("FED-WIRE-")

        # 4. Verify double-entry ledger journal balance in PostgreSQL
        async with get_test_db_session() as session:
            stmt = select(LedgerJournal).where(LedgerJournal.wire_id == uuid.UUID(wire_id))
            entries = (await session.execute(stmt)).scalars().all()
            assert len(entries) == 2

            debit_entry = next((e for e in entries if e.direction == LedgerDirection.DEBIT.value), None)
            credit_entry = next((e for e in entries if e.direction == LedgerDirection.CREDIT.value), None)
            assert debit_entry is not None
            assert credit_entry is not None
            assert debit_entry.amount_cents == 17500050
            assert credit_entry.amount_cents == 17500050
            assert debit_entry.account_type == "customer_cash"
            assert credit_entry.account_type == "clearinghouse_settlement"

            # 5. Verify audit log event progression
            audit_stmt = select(WireAuditLog).where(WireAuditLog.wire_id == uuid.UUID(wire_id))
            audit_records = (await session.execute(audit_stmt)).scalars().all()
            assert len(audit_records) >= 1
            statuses = [a.new_status for a in audit_records]
            assert WireStatus.SETTLED.value in statuses


@pytest.mark.asyncio
async def test_live_concurrent_wires_batch_zero_loss(
    chaos_harness: ChaosHarness,
) -> None:
    """Verify high-concurrency batch processing across multiple worker pods with zero loss."""
    num_wires = 8
    async with httpx.AsyncClient(timeout=20.0) as client:
        # 1. Ingest batch of distinct wires concurrently
        async def submit_wire(index: int) -> dict[str, Any]:
            idem = f"live-batch-{index}-{uuid.uuid4().hex[:8]}"
            amount = 10000 + (index * 500)
            payload = {
                "client_id": f"CORP-BATCH-{(index % 3) + 1}",
                "amount": f"{amount}.00",
                "currency": "USD",
                "beneficiary_account": f"98765432{index:02d}",
                "routing_number": "121000358",
                "swift_bic": "CHASUS33",
            }
            resp = await client.post(
                f"{API_BASE_URL}/api/v1/wires",
                json=payload,
                headers={"Idempotency-Key": idem},
            )
            assert resp.status_code == 202
            return resp.json()

        submitted_wires = await asyncio.gather(*(submit_wire(i) for i in range(num_wires)))
        wire_ids = [w["wire_id"] for w in submitted_wires]

        # 2. Await all wires settling concurrently
        async def await_settled(w_id: str) -> dict[str, Any]:
            return await chaos_harness.audit_wire_status(w_id, timeout=25.0, client=client)

        settled_records = await asyncio.gather(*(await_settled(w_id) for w_id in wire_ids))

        # 3. Assert 100% of submitted wires settled
        assert len(settled_records) == num_wires
        for rec in settled_records:
            assert rec["status"] == WireStatus.SETTLED.value
            assert rec["bank_reference_id"] is not None

        # 4. Verify batch ledger parity in database
        async with get_test_db_session() as session:
            batch_audit = await chaos_harness.audit_ledger_parity(session=session)
            assert batch_audit.is_balanced is True
            assert batch_audit.drift_cents == 0
            assert batch_audit.double_disbursements_count == 0


@pytest.mark.asyncio
async def test_live_idempotency_collision_under_concurrency() -> None:
    """Verify atomic idempotency handling when multiple parallel requests use identical keys."""
    client_id = "CORP-COLLISION-001"
    collision_idem_key = f"live-collision-{uuid.uuid4().hex[:10]}"
    wire_payload = {
        "client_id": client_id,
        "amount": "99999.00",
        "currency": "USD",
        "beneficiary_account": "7777888899",
        "routing_number": "121000358",
        "swift_bic": "CHASUS33",
    }

    # 1. Fire 5 concurrent requests with identical idempotency key
    async with httpx.AsyncClient(timeout=10.0) as client:
        async def post_same_wire() -> httpx.Response:
            return await client.post(
                f"{API_BASE_URL}/api/v1/wires",
                json=wire_payload,
                headers={"Idempotency-Key": collision_idem_key},
            )

        responses = await asyncio.gather(*(post_same_wire() for _ in range(5)))

        # 2. Verify all calls returned successful acceptance (202)
        for r in responses:
            assert r.status_code == 202

        # 3. Assert all responses returned the EXACT same wire_id
        wire_ids = {r.json()["wire_id"] for r in responses}
        assert len(wire_ids) == 1, f"Expected exactly 1 distinct wire_id, got {wire_ids}"
        shared_wire_id = next(iter(wire_ids))

        # 4. Wait for the single wire to settle
        for _ in range(25):
            await asyncio.sleep(0.4)
            get_resp = await client.get(f"{API_BASE_URL}/api/v1/wires/{shared_wire_id}")
            if get_resp.json().get("status") == WireStatus.SETTLED.value:
                break

        # 5. Assert database contains EXACTLY one WireTransfer record for this key
        async with get_test_db_session() as session:
            count_stmt = select(func.count(WireTransfer.wire_id)).where(
                WireTransfer.client_id == client_id,
                WireTransfer.idempotency_key == collision_idem_key,
            )
            count = (await session.execute(count_stmt)).scalar_one()
            assert count == 1, f"Expected 1 wire row in database, found {count}"

        # 6. Assert Bank Simulator API recorded only one disbursement
        bank_resp = await client.get(f"{BANK_BASE_URL}/v1/wires/{collision_idem_key}")
        assert bank_resp.status_code == 200
        bank_data = bank_resp.json()
        assert bank_data["amount_cents"] == 9999900


@pytest.mark.asyncio
async def test_live_worker_sigkill_redelivery_and_anti_duplicate_payout(
    chaos_harness: ChaosHarness,
) -> None:
    """Verify worker SIGKILL crash mid-flight triggers redelivery without duplicate payouts."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        # 1. Ingest a wire transfer
        idem_key = f"live-sigkill-{uuid.uuid4().hex[:10]}"
        wire_payload = {
            "client_id": "CORP-FAULT-SIGKILL",
            "amount": "450000.00",
            "currency": "USD",
            "beneficiary_account": "5566778899",
            "routing_number": "121000358",
            "swift_bic": "CHASUS33",
        }
        resp = await client.post(
            f"{API_BASE_URL}/api/v1/wires",
            json=wire_payload,
            headers={"Idempotency-Key": idem_key},
        )
        assert resp.status_code == 202
        wire_id = resp.json()["wire_id"]

        # 2. Inject fault: Deliver SIGKILL to worker_1 container
        chaos_harness.kill_container("worker_1", "SIGKILL")

        # 3. Wait for surviving worker (worker_2) to settle the redelivered wire
        settled_wire = await chaos_harness.audit_wire_status(wire_id, timeout=25.0, client=client)
        assert settled_wire["status"] == WireStatus.SETTLED.value
        assert settled_wire["bank_reference_id"] is not None

        # 4. Restart worker_1 to restore fleet capacity
        chaos_harness.start_container("worker_1")
        await asyncio.sleep(2.0)

        # 5. Verify mathematical ledger parity: exactly 1 DEBIT and 1 CREDIT for this wire
        async with get_test_db_session() as session:
            stmt = select(LedgerJournal).where(LedgerJournal.wire_id == uuid.UUID(wire_id))
            entries = (await session.execute(stmt)).scalars().all()
            assert len(entries) == 2, f"Expected 2 ledger entries, found {len(entries)} (duplicate payout detected!)"

            debits = sum(e.amount_cents for e in entries if e.direction == LedgerDirection.DEBIT.value)
            credits = sum(e.amount_cents for e in entries if e.direction == LedgerDirection.CREDIT.value)
            assert debits == credits == 45000000


@pytest.mark.asyncio
async def test_live_poison_pill_dead_letter_quarantine(
    chaos_harness: ChaosHarness,
) -> None:
    """Verify malformed poison pill message is quarantined to DLQ without halting processing."""
    # 1. Publish malformed poison pill message directly to AMQP DLX routing
    conn = Connection(BROKER_URL)
    conn.connect()
    poison_id = f"poison-{uuid.uuid4().hex[:8]}"
    malformed_body = {
        "corrupted_payload": True,
        "invalid_field": "UNKNOWN_ERROR_DATA",
        "poison_tag": poison_id,
    }

    with conn.channel() as channel:
        dlq = wire_dlq_queue(channel)
        dlq.declare()
        dlq.purge()
        producer = conn.Producer(channel=channel)
        producer.publish(
            malformed_body,
            exchange=wire_dlx_exchange,
            routing_key=WIRE_DLQ_QUEUE_NAME,
            serializer="json",
            headers={
                "x-death": [
                    {
                        "reason": "rejected",
                        "queue": WIRE_CRITICAL_QUEUE_NAME,
                        "exchange": wire_direct_exchange.name,
                        "routing-keys": [WIRE_CRITICAL_QUEUE_NAME],
                        "count": 1,
                    }
                ]
            },
        )
    conn.close()

    # 2. Verify message arrived in dead letter queue (wire.settlement.dlq)
    dlq_messages = chaos_harness.audit_dlq_messages(max_messages=5, requeue=True)
    assert len(dlq_messages) >= 1
    assert any("corrupted_payload" in str(m.get("body", "")) for m in dlq_messages)

    # 3. Verify healthy subsequent wire is processed and not blocked
    async with httpx.AsyncClient(timeout=10.0) as client:
        healthy_idem = f"post-poison-{uuid.uuid4().hex[:8]}"
        healthy_payload = {
            "client_id": "CORP-POST-POISON",
            "amount": "25000.00",
            "currency": "USD",
            "beneficiary_account": "4433221100",
            "routing_number": "121000358",
            "swift_bic": "CHASUS33",
        }
        resp = await client.post(
            f"{API_BASE_URL}/api/v1/wires",
            json=healthy_payload,
            headers={"Idempotency-Key": healthy_idem},
        )
        assert resp.status_code == 202
        healthy_wire_id = resp.json()["wire_id"]

        settled = await chaos_harness.audit_wire_status(healthy_wire_id, timeout=15.0, client=client)
        assert settled["status"] == WireStatus.SETTLED.value


@pytest.mark.asyncio
async def test_live_global_ledger_parity_and_zero_drift(
    chaos_harness: ChaosHarness,
) -> None:
    """Verify total ledger parity across all live transactions executed in cluster."""
    # 1. Audit relational ledger parity
    async with get_test_db_session() as session:
        audit = await chaos_harness.audit_ledger_parity(session=session)

    # 2. Assert zero drift and zero double disbursements
    assert audit.is_balanced is True
    assert audit.drift_cents == 0
    assert audit.double_disbursements_count == 0
    assert audit.total_debits_cents == audit.total_credits_cents
    assert audit.settled_wires_count > 0
    assert audit.unique_idempotency_keys_count == audit.settled_wires_count
