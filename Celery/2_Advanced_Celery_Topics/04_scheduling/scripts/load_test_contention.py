"""Automated Capacity & Contention Benchmark Script for EOD Banking Reconciliation.

Simulates heavy concurrent ledger transaction volume and report queries while an asynchronous
End-of-Day (EOD) cut-off reconciliation job and historical gap backfill execute in the background.
Measures both API Ingestion Latency under saturation and Worker End-to-End Clearing SLA,
and persists structured JSON metrics to disk for regression tracking and performance auditing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("contention_benchmark")

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports" / "benchmarks"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


async def pre_seed_ledger_records(
    client: httpx.AsyncClient,
    period_date: str,
    count: int = 50,
) -> int:
    """Pre-seed synthetic balanced and discrepancy ledger records for benchmark testing.

    Args:
        client: HTTPX asynchronous client connected to API Gateway.
        period_date: Financial business period date string ('YYYY-MM-DD').
        count: Number of ledger seed batches to execute.

    Returns:
        int: Total number of ledger transactions created.
    """
    logger.info("Pre-seeding %d synthetic ledger batches for period %s...", count, period_date)
    created_total = 0
    for idx in range(count):
        scenario = "balanced" if idx % 4 != 0 else "discrepancy"
        amount = 10000 + (idx * 250)
        payload = {
            "period_date": period_date,
            "scenario": scenario,
            "amount_cents": amount,
        }
        try:
            res = await client.post("/seed", json=payload)
            if res.status_code == 201:
                created_total += res.json().get("entries_created", 2)
        except Exception as exc:
            logger.warning("Seeding batch %d failed: %s", idx, exc)
    logger.info("Pre-seeded %d total double-entry ledger records", created_total)
    return created_total


async def run_contention_benchmark(
    api_url: str = "http://localhost:8000",
    seed_count: int = 50,
    probes_count: int = 100,
    rate: float = 100.0,
    output_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Run EOD cut-off and ledger reconciliation contention benchmark.

    Args:
        api_url: Base URL of the API gateway.
        seed_count: Number of ledger batches to pre-seed prior to cut-off trigger.
        probes_count: Number of concurrent API probes to dispatch during reconciliation.
        rate: Little's Law probe arrival rate in requests/sec (0 for unconstrained burst).
        output_path: Optional custom path to persist structured benchmark JSON.

    Returns:
        dict[str, Any] | None: Structured benchmark results report, or None on failure.
    """
    period_date_str = date.today().isoformat()
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)

    async with httpx.AsyncClient(base_url=api_url, limits=limits, timeout=30.0) as client:
        # 1. Verify API Gateway Health
        try:
            health_res = await client.get("/health")
            if health_res.status_code != 200:
                logger.error("API Gateway not healthy (HTTP %d)", health_res.status_code)
                return None
        except Exception as exc:
            logger.error("Could not connect to API Gateway at %s: %s", api_url, exc)
            return None

        logger.info("=================================================================")
        logger.info("STARTING EOD RECONCILIATION CONTENTION BENCHMARK")
        mode_desc = f"Paced at {rate:.1f} req/s" if rate > 0 else "Unconstrained burst"
        logger.info("Target: %s | Probes: %d | Mode: %s", api_url, probes_count, mode_desc)
        logger.info("=================================================================")

        # 2. Pre-seed initial ledger transactions
        t0_seed = time.perf_counter()
        entries_count = await pre_seed_ledger_records(client, period_date_str, count=seed_count)
        t_seed_ms = (time.perf_counter() - t0_seed) * 1000.0

        # 3. Trigger background EOD reconciliation cut-off and gap backfill
        logger.info("Step 1: Enqueuing background EOD reconciliation cut-off job...")
        reconcile_payload = {
            "period_date": period_date_str,
            "clearing_variance_cents": 0,
            "force": True,
        }
        t0_dispatch = time.perf_counter()
        rec_res = await client.post("/reconciliations/trigger", json=reconcile_payload)
        t_rec_dispatch_ms = (time.perf_counter() - t0_dispatch) * 1000.0

        if rec_res.status_code != 202:
            logger.error("Failed to trigger reconciliation: HTTP %d", rec_res.status_code)
            return None

        task_id = rec_res.json().get("task_id", "unknown")
        logger.info("Reconciliation enqueued with task_id=%s in %.2f ms", task_id, t_rec_dispatch_ms)

        # Trigger background gap backfill to create realistic worker task queue competition
        backfill_res = await client.post("/reconciliations/backfill", json={})
        logger.info("Backfill enqueued with status HTTP %d", backfill_res.status_code)

        # 4. Fire API probes while reconciliation executes in the background
        logger.info(
            "Step 2: Dispatching %d API probes under background worker reconciliation...",
            probes_count,
        )

        async def send_probe(probe_idx: int) -> tuple[float, bool]:
            """Send a single probe (alternating between seed writes and read queries)."""
            t_start = time.perf_counter()
            success = False
            try:
                if probe_idx % 3 == 0:
                    # Write probe: seed small transaction batch
                    r = await client.post(
                        "/seed",
                        json={
                            "period_date": period_date_str,
                            "scenario": "balanced",
                            "amount_cents": 5000 + probe_idx,
                        },
                    )
                    success = r.status_code == 201
                elif probe_idx % 3 == 1:
                    # Read probe: query paginated reconciliations
                    r = await client.get("/reconciliations?limit=20&offset=0")
                    success = r.status_code == 200
                else:
                    # Read probe: audit business-day gaps
                    r = await client.get("/reconciliations/gaps")
                    success = r.status_code == 200
            except Exception as exc:
                logger.warning("Probe %d encountered error: %s", probe_idx, exc)
                success = False

            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            return elapsed_ms, success

        # Pre-warm HTTP keep-alive connections
        for w_idx in range(5):
            await send_probe(w_idx)

        latencies_ms: list[float] = []
        successes = 0

        if rate > 0:
            interval = 1.0 / rate
            for idx in range(probes_count):
                t_iter_start = time.perf_counter()
                elapsed, ok = await send_probe(idx)
                latencies_ms.append(elapsed)
                if ok:
                    successes += 1
                sleep_time = interval - (time.perf_counter() - t_iter_start)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
        else:
            gather_tasks = [send_probe(i) for i in range(probes_count)]
            results = await asyncio.gather(*gather_tasks)
            latencies_ms = [r[0] for r in results]
            successes = sum(1 for r in results if r[1])

        # 5. Compute API Ingestion Latency statistics
        latencies_ms.sort()
        p50 = statistics.median(latencies_ms)
        p95 = latencies_ms[min(int(len(latencies_ms) * 0.95), len(latencies_ms) - 1)]
        p99 = latencies_ms[min(int(len(latencies_ms) * 0.99), len(latencies_ms) - 1)]
        mean = statistics.mean(latencies_ms)
        min_lat = min(latencies_ms)
        max_lat = max(latencies_ms)

        logger.info("=================================================================")
        logger.info("BENCHMARK RESULTS: API INGESTION ROUNDTRIP UNDER CONTENTION")
        logger.info("Probes Dispatched: %d (%d successful)", len(latencies_ms), successes)
        logger.info("Min: %.2f ms | Mean: %.2f ms | Max: %.2f ms", min_lat, mean, max_lat)
        logger.info("P50: %.2f ms | P95: %.2f ms | P99: %.2f ms", p50, p95, p99)

        if p99 <= 100.0:
            logger.info("SUCCESS: API Ingestion P99 latency (%.2f ms) is within 100 ms SLA!", p99)
        else:
            logger.warning("WARNING: API Ingestion P99 latency (%.2f ms) exceeded 100 ms SLA threshold", p99)

        # 6. Measure Worker-Side EOD Clearing SLA
        logger.info("=================================================================")
        logger.info("Step 3: Polling reconciliation report completion from database...")
        clearing_duration_ms: float | None = None
        for _ in range(60):
            await asyncio.sleep(0.05)
            report_res = await client.get(f"/reconciliations/{period_date_str}")
            if report_res.status_code == 200:
                data = report_res.json()
                if data.get("status") in ("balanced", "discrepancy"):
                    clearing_duration_ms = (time.perf_counter() - t0_dispatch) * 1000.0
                    logger.info(
                        "Reconciliation report finalized: status=%s, clearing_duration=%.2f ms",
                        data.get("status"),
                        clearing_duration_ms,
                    )
                    break

        worker_sla_passed = clearing_duration_ms is not None and clearing_duration_ms <= 500.0
        if clearing_duration_ms is not None:
            logger.info("Worker EOD cut-off clearing duration: %.2f ms", clearing_duration_ms)
            if worker_sla_passed:
                logger.info("SUCCESS: Worker clearing duration is within 500 ms SLA threshold!")
            else:
                logger.warning("WARNING: Worker clearing duration exceeded 500 ms SLA threshold")
        else:
            logger.info("Worker asynchronous task still processing in background")

        logger.info("=================================================================")

        # 7. Construct and persist structured JSON benchmark report
        timestamp_now = datetime.now(timezone.utc)
        report: dict[str, Any] = {
            "timestamp": timestamp_now.isoformat(),
            "environment": {
                "api_url": api_url,
                "mode": "paced" if rate > 0 else "burst",
                "arrival_rate_req_sec": rate,
            },
            "parameters": {
                "pre_seed_batches": seed_count,
                "total_pre_seeded_entries": entries_count,
                "probes_count": probes_count,
                "period_date": period_date_str,
            },
            "seeding_duration_ms": round(t_seed_ms, 2),
            "reconciliation_dispatch_duration_ms": round(t_rec_dispatch_ms, 2),
            "api_ingestion_latency_ms": {
                "count": len(latencies_ms),
                "successful": successes,
                "min": round(min_lat, 2),
                "mean": round(mean, 2),
                "p50": round(p50, 2),
                "p95": round(p95, 2),
                "p99": round(p99, 2),
                "max": round(max_lat, 2),
                "sla_threshold_ms": 100.0,
                "sla_passed": p99 <= 100.0,
            },
            "worker_clearing_latency_ms": {
                "sample_size": 1 if clearing_duration_ms is not None else 0,
                "duration_ms": round(clearing_duration_ms, 2) if clearing_duration_ms is not None else None,
                "sla_threshold_ms": 500.0,
                "sla_passed": worker_sla_passed,
            }
            if clearing_duration_ms is not None
            else None,
        }

        # 8. Persist to reports/benchmarks
        if output_path:
            file_path = Path(output_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            time_str = timestamp_now.strftime("%Y%m%d_%H%M%S")
            file_path = REPORTS_DIR / f"benchmark_{time_str}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        latest_path = REPORTS_DIR / "latest.json"
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info("Persisted benchmark report to %s and %s", file_path, latest_path)
        return report


def main() -> None:
    """Parse CLI options and execute the EOD contention benchmark."""
    parser = argparse.ArgumentParser(description="EOD Banking Cut-Off & Ledger Reconciliation Contention Benchmark")
    parser.add_argument(
        "--url",
        "--gateway-url",
        dest="url",
        default="http://localhost:8000",
        help="API Gateway URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--seed-count",
        type=int,
        default=50,
        help="Number of synthetic ledger batches to pre-seed (default: 50)",
    )
    parser.add_argument(
        "--probes",
        type=int,
        default=100,
        help="Number of API probes to dispatch (default: 100)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=100.0,
        help="Probe arrival rate in req/s (default: 100.0; set 0 for burst)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional custom path to save benchmark JSON report",
    )

    args = parser.parse_args()
    asyncio.run(
        run_contention_benchmark(
            api_url=args.url,
            seed_count=args.seed_count,
            probes_count=args.probes,
            rate=args.rate,
            output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
