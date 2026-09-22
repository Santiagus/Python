"""Batch Chunk Sizing & Clearing Velocity Benchmarking Engine.

Empirically benchmarks Celery batch clearing velocity and database contention
across varying chunk sizes (N in [25, 50, 100, 250, 500]) on high-performance
multi-core hardware (e.g. AMD Ryzen 9 7900 - 12 cores / 24 threads).

Validates the mathematical coupling between Celery's token-bucket rate limiter
('500/m' -> 8.33 chunks/s) and effective item throughput (items/s and items/min).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any
from uuid import UUID, uuid4

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.dispatcher import PaymentDispatcher
from app.models import Account, BatchSettlement, Disbursement
from services.worker.celery_app import celery_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark_chunks")

SOURCE_BATCH_ACCOUNT_ID = UUID("a0000000-0000-0000-0000-000000000002")
DESTINATION_ROUTING = "021000021"


def purge_bulk_queue() -> int:
    """Purge leftover tasks from the RabbitMQ bulk queue before testing.

    Returns:
        int: Number of purged messages.
    """
    with celery_app.connection_or_acquire() as conn:
        with conn.channel() as channel:
            return channel.queue_purge("bulk") or 0


def configure_worker_rate_limit(rate_limit: str | None) -> None:
    """Dynamically set the task rate limit across all live Celery workers.

    Args:
        rate_limit: Rate limit string (e.g. '500/m', '3000/m', 'none', or '0').
    """
    task_name = "services.worker.tasks.settlements.process_payroll_chunk"
    val: str | int = 0 if (rate_limit is None or str(rate_limit).lower() in ("none", "0", "off", "unconstrained")) else rate_limit
    res = celery_app.control.rate_limit(task_name, val, reply=True)
    logger.info(f"Broadcasted task rate limit '{val}' across worker fleet: {res}")


async def ensure_source_account(session: AsyncSession) -> None:
    """Ensure the funding payroll source account exists in PostgreSQL.

    Args:
        session: Active async SQLAlchemy database session.
    """
    stmt = select(Account).where(Account.account_id == SOURCE_BATCH_ACCOUNT_ID)
    res = await session.execute(stmt)
    account = res.scalar_one_or_none()
    if not account:
        logger.info("creating_missing_payroll_account", extra={"account_id": str(SOURCE_BATCH_ACCOUNT_ID)})
        account = Account(
            account_id=SOURCE_BATCH_ACCOUNT_ID,
            account_holder="Enterprise Payroll Clearing Corp",
            account_number="222200001111",
            routing_number="021000021",
            balance_cents=1000000000,  # $10,000,000.00
            currency="USD",
        )
        session.add(account)
        await session.commit()


async def run_single_chunk_benchmark(
    batch_size: int,
    chunk_size: int,
    poll_interval: float = 0.05,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Execute a single batch clearing benchmark run for a specific chunk size.

    Args:
        batch_size: Total disbursement line items in the test batch.
        chunk_size: Slicing granularity for Celery task chunks.
        poll_interval: Seconds between PostgreSQL completion status checks.
        timeout_seconds: Maximum seconds before aborting the run.

    Returns:
        dict[str, Any]: Detailed execution metrics dictionary.
    """
    session_factory = get_session_factory()
    dispatcher = PaymentDispatcher()

    # 1. Clean up broker queue
    purged = purge_bulk_queue()
    if purged > 0:
        logger.warning(f"Purged {purged} stale messages from 'bulk' queue prior to test.")

    # 2. Persist parent BatchSettlement and child Disbursements
    batch_uuid = uuid4()
    file_ref = f"bench_chunk_{chunk_size}_{uuid4().hex[:6]}"
    item_uuids: list[UUID] = [uuid4() for _ in range(batch_size)]
    item_id_strs: list[str] = [str(u) for u in item_uuids]

    t_db_start = time.perf_counter()
    async with session_factory() as session:
        await ensure_source_account(session)

        batch = BatchSettlement(
            batch_id=batch_uuid,
            file_reference=file_ref,
            source_account_id=SOURCE_BATCH_ACCOUNT_ID,
            total_items=batch_size,
            total_amount_cents=batch_size * 15000,  # $150.00 per item
            processed_items=0,
            status="pending",
        )
        session.add(batch)
        await session.flush()

        disbursement_objects = [
            Disbursement(
                disbursement_id=uid,
                batch_id=batch_uuid,
                recipient_name=f"Worker {idx}",
                account_number=f"2222{idx:08d}",
                routing_number=DESTINATION_ROUTING,
                amount_cents=15000,
                status="pending",
            )
            for idx, uid in enumerate(item_uuids)
        ]
        session.add_all(disbursement_objects)
        await session.commit()

    db_persist_duration = time.perf_counter() - t_db_start

    # 3. Dispatch chunks to RabbitMQ bulk queue
    t_dispatch_start = time.perf_counter()
    task_handles = dispatcher.dispatch_batch_settlement(
        batch_id=batch_uuid,
        disbursement_ids=item_id_strs,
        chunk_size=chunk_size,
        correlation_id=f"corr_{file_ref}",
    )
    dispatch_duration = time.perf_counter() - t_dispatch_start
    total_chunks = len(task_handles)

    # 4. Poll database until all items are marked completed
    t_clearing_start = time.perf_counter()
    deadline = t_clearing_start + timeout_seconds
    final_processed = 0
    final_status = "pending"

    while time.perf_counter() < deadline:
        async with session_factory() as session:
            stmt = select(BatchSettlement).where(BatchSettlement.batch_id == batch_uuid)
            res = await session.execute(stmt)
            b = res.scalar_one()
            final_processed = b.processed_items
            final_status = b.status

            if b.status == "completed" or final_processed >= batch_size:
                break

        await asyncio.sleep(poll_interval)

    t_clearing_end = time.perf_counter()
    clearing_duration = t_clearing_end - t_clearing_start

    if final_status != "completed" and final_processed < batch_size:
        raise TimeoutError(
            f"Chunk benchmark timed out for chunk_size={chunk_size} after {timeout_seconds:.1f}s. "
            f"Processed {final_processed}/{batch_size} items."
        )

    # 5. Compute derived velocity metrics
    items_per_second = batch_size / clearing_duration if clearing_duration > 0 else 0.0
    effective_items_per_minute = items_per_second * 60.0
    chunks_per_second = total_chunks / clearing_duration if clearing_duration > 0 else 0.0
    token_bucket_utilization = (chunks_per_second / 8.333) * 100.0  # 500/m = 8.333 chunks/s

    return {
        "chunk_size": chunk_size,
        "batch_size": batch_size,
        "total_chunks": total_chunks,
        "db_persist_duration_ms": round(db_persist_duration * 1000.0, 2),
        "dispatch_duration_ms": round(dispatch_duration * 1000.0, 2),
        "clearing_duration_s": round(clearing_duration, 3),
        "items_per_second": round(items_per_second, 1),
        "effective_items_per_minute": round(effective_items_per_minute, 0),
        "chunks_per_second": round(chunks_per_second, 2),
        "token_bucket_utilization_pct": round(token_bucket_utilization, 1),
    }


async def run_chunk_benchmark_suite(
    batch_size: int,
    chunk_sizes: list[int],
    output_dir: Path,
    rate_limit: str | None = "500/m",
) -> dict[str, Any]:
    """Orchestrate the multi-scale chunk benchmark sweep.

    Args:
        batch_size: Batch volume for each trial.
        chunk_sizes: List of chunk slice sizes to evaluate.
        output_dir: Destination directory for JSON artifact reports.
        rate_limit: Celery task rate limit (e.g. '500/m', '3000/m', 'none').

    Returns:
        dict[str, Any]: Full structured summary report.
    """
    configure_worker_rate_limit(rate_limit)

    logger.info("=" * 78)
    logger.info("CELERY BATCH CHUNK SIZING & CLEARING VELOCITY BENCHMARK")
    logger.info(f"Target Batch Size: {batch_size:,} disbursement items per trial")
    logger.info(f"Chunk Sizes Evaluated: {chunk_sizes}")
    logger.info(f"Rate Limit Policy: {rate_limit or 'unconstrained'}")
    logger.info("=" * 78)

    results: list[dict[str, Any]] = []

    for chunk_size in chunk_sizes:
        logger.info(f"--> Benchmarking chunk_size={chunk_size} ({batch_size // chunk_size} chunks)...")
        res = await run_single_chunk_benchmark(batch_size=batch_size, chunk_size=chunk_size)
        results.append(res)
        logger.info(
            f"    Result: {res['clearing_duration_s']:.2f}s | "
            f"{res['items_per_second']} items/s ({int(res['effective_items_per_minute']):,} items/min) | "
            f"{res['chunks_per_second']} chunks/s"
        )
        # Brief pause between trials for queue & db drain
        await asyncio.sleep(1.0)

    # Calculate speedup relative to N=100 baseline
    baseline_speed = next(
        (r["items_per_second"] for r in results if r["chunk_size"] == 100),
        results[0]["items_per_second"],
    )
    for r in results:
        r["speedup_vs_n100"] = round(r["items_per_second"] / baseline_speed, 2)

    # Synthesize JSON artifact
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "benchmark_type": "celery_batch_chunk_sizing",
        "timestamp": timestamp,
        "hardware": {
            "processor": "AMD Ryzen 9 7900 (12 cores / 24 threads)",
            "memory": "32 GB DDR5",
        },
        "topology": {
            "worker_bulk_concurrency": 2,
            "worker_bulk_prefetch": 4,
            "rate_limit_policy": rate_limit or "unconstrained",
        },
        "batch_size": batch_size,
        "results": results,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / f"chunk_benchmark_{timestamp}.json"
    latest_file = output_dir / "chunk_latest.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Saved benchmark report to: {report_file}")
    logger.info(f"Updated latest report link: {latest_file}")

    # Print clean Markdown summary table
    print("\n" + "=" * 92)
    print("EMPIRICAL CHUNK SIZING & CLEARING VELOCITY TABLE")
    print("=" * 92)
    print(
        f"{'Chunk Size (N)':<16} | {'Chunks':<8} | {'Clearing (s)':<14} | "
        f"{'Items / s':<12} | {'Items / min':<14} | {'Speedup vs N=100':<16}"
    )
    print("-" * 92)
    for r in results:
        print(
            f"{r['chunk_size']:<16} | {r['total_chunks']:<8} | {r['clearing_duration_s']:<14.2f} | "
            f"{r['items_per_second']:<12.1f} | {int(r['effective_items_per_minute']):<14,d} | "
            f"{r['speedup_vs_n100']:<16.2f}x"
        )
    print("=" * 92 + "\n")

    return report


def main() -> None:
    """CLI entry point for chunk sizing benchmark."""
    parser = argparse.ArgumentParser(description="Celery Batch Chunk Sizing Benchmark")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Number of disbursements per trial (default: 2000)",
    )
    parser.add_argument(
        "--chunk-sizes",
        type=int,
        nargs="+",
        default=[25, 50, 100, 250, 500],
        help="Chunk sizes to test (default: 25 50 100 250 500)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/benchmarks"),
        help="Directory to save JSON reports (default: reports/benchmarks)",
    )
    parser.add_argument(
        "--rate-limit",
        type=str,
        default="500/m",
        help="Celery task rate limit policy (e.g. '500/m', '3000/m', '5000/m', 'none'; default: '500/m')",
    )
    args = parser.parse_args()

    asyncio.run(
        run_chunk_benchmark_suite(
            batch_size=args.batch_size,
            chunk_sizes=args.chunk_sizes,
            output_dir=args.output_dir,
            rate_limit=args.rate_limit,
        )
    )


if __name__ == "__main__":
    main()
