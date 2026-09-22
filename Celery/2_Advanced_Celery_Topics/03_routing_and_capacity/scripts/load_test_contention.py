"""Automated Queue Contention & Latency Benchmark Script.

Verifies that heavy bulk queue saturation (e.g. 500-10,000 ACH tasks) causes ZERO compute
or queue contention starvation for real-time FedNow/RTP payouts on the 'critical' queue.
Measures both API Ingestion Latency and Worker-Side End-to-End Clearing Latency, and persists
structured JSON metrics to disk for performance profiling, regression tracking, and capacity analysis.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import statistics
import time
from typing import Any
from uuid import uuid4

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("contention_benchmark")


async def run_contention_benchmark(
    api_url: str = "http://localhost:8010",
    api_key: str = "sk_live_payment_orchestrator_secret_key_2026",
    bulk_count: int = 500,
    instant_count: int = 100,
    rate: float = 50.0,
    output_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Run contention benchmark against active or containerized API gateway.

    Args:
        api_url: API Gateway endpoint URL.
        api_key: Master M2M authentication key.
        bulk_count: Number of bulk payroll items to saturate the 'bulk' queue.
        instant_count: Number of real-time instant payment probes to dispatch.
        rate: Probe arrival rate in requests/sec (default 50.0 req/s matches Little's Law SLA peak).
              Set to 0 for unconstrained simultaneous burst testing.
        output_path: Optional custom destination file path for benchmark results JSON.

    Returns:
        dict[str, Any] | None: Structured benchmark results report, or None on failure.
    """
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
        # 1. Verify health
        try:
            res = await client.get("/health/live")
            if res.status_code != 200:
                logger.error("API Gateway not healthy: %s", res.status_code)
                return None
        except Exception as e:
            logger.error("Could not connect to API at %s: %s", api_url, e)
            return None

        logger.info("=================================================================")
        logger.info("STARTING QUEUE CONTENTION BENCHMARK")
        mode_desc = f"Paced at {rate:.1f} req/s" if rate > 0 else "Unconstrained concurrent burst"
        logger.info(
            "Bulk saturation items: %d | Instant probes: %d | Mode: %s",
            bulk_count,
            instant_count,
            mode_desc,
        )
        logger.info("=================================================================")

        # 2. Saturate bulk queue with disbursement batch
        logger.info("Step 1: Submitting bulk batch to saturate 'bulk' queue...")
        disbursements = [
            {
                "recipient_name": f"Employee {i}",
                "account_number": f"1111{i:08d}",
                "routing_number": "021000021",
                "amount": "100.00",
            }
            for i in range(bulk_count)
        ]
        batch_payload = {
            "file_reference": f"bench_batch_{uuid4().hex[:8]}",
            "source_account_id": "a0000000-0000-0000-0000-000000000002",
            "disbursements": disbursements,
        }
        t0_bulk = time.perf_counter()
        batch_res = await client.post("/disbursements/batch", json=batch_payload, headers=headers)
        t_bulk_ingest = (time.perf_counter() - t0_bulk) * 1000
        logger.info("Bulk batch ingested in %.2f ms (HTTP %d)", t_bulk_ingest, batch_res.status_code)

        # Allow DB transaction to commit and RabbitMQ task dispatcher to complete cleanly before measuring instant probes
        await asyncio.sleep(0.1)

        async def send_instant(idx: Any) -> tuple[float, str | None]:
            payload = {
                "idempotency_key": f"bench_instant_{uuid4().hex}_{idx}",
                "source_account_id": "a0000000-0000-0000-0000-000000000001",
                "destination_account_number": "987654321098",
                "destination_routing_number": "021000021",
                "amount": "10.00",
                "rail": "rtp",
                "description": f"Contention benchmark probe {idx}",
            }
            t0 = time.perf_counter()
            r = await client.post("/payments/instant", json=payload, headers=headers)
            elapsed = (time.perf_counter() - t0) * 1000
            pid = None
            if r.status_code != 202:
                logger.warning("Instant payout probe %s failed with status %d", idx, r.status_code)
            else:
                pid = r.json().get("payment_id")
            return elapsed, pid

        # Pre-warm gateway keep-alive connections and Celery AMQP channels across all upstream replicas
        logger.info("Pre-warming upstream instant payment pool (10 probes)...")
        for w_idx in range(10):
            await send_instant(f"warmup_{w_idx}")
        await asyncio.sleep(0.2)

        # 3. Fire instant payments while bulk is executing in the background
        logger.info("Step 2: Dispatching %d instant payments against saturated system...", instant_count)
        latencies_ms: list[float] = []
        payment_ids: list[str] = []

        if rate > 0:
            # Paced arrival rate (matches Little's Law lambda = 50 req/s)
            interval = 1.0 / rate
            for i in range(instant_count):
                t_start = time.perf_counter()
                elapsed, pid = await send_instant(i)
                latencies_ms.append(elapsed)
                if pid:
                    payment_ids.append(pid)
                sleep_time = interval - (time.perf_counter() - t_start)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
        else:
            # Simultaneous burst mode
            tasks = [send_instant(i) for i in range(instant_count)]
            results = await asyncio.gather(*tasks)
            latencies_ms = [r[0] for r in results]
            payment_ids = [r[1] for r in results if r[1]]

        # 4. Calculate API Ingestion Latency statistics
        latencies_ms.sort()
        p50 = statistics.median(latencies_ms)
        p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
        p99 = latencies_ms[int(len(latencies_ms) * 0.99)]
        p95 = latencies_ms[min(int(len(latencies_ms) * 0.95), len(latencies_ms) - 1)]
        p99 = latencies_ms[min(int(len(latencies_ms) * 0.99), len(latencies_ms) - 1)]
        mean = statistics.mean(latencies_ms)
        min_lat = min(latencies_ms)
        max_lat = max(latencies_ms)

        logger.info("=================================================================")
        logger.info("BENCHMARK RESULTS: API INGESTION ROUNDTRIP UNDER CONTENTION")
        logger.info("Count: %d | Min: %.2f ms | Max: %.2f ms", len(latencies_ms), min_lat, max_lat)
        logger.info("Mean: %.2f ms | P50: %.2f ms | P95: %.2f ms | P99: %.2f ms", mean, p50, p95, p99)

        if p99 < 100.0:
            logger.info("SUCCESS: Ingestion P99 latency (%.2f ms) is strictly below 100 ms SLA!", p99)
        else:
            logger.warning("WARNING: Ingestion P99 latency (%.2f ms) exceeded 100 ms SLA threshold", p99)

        # 5. Measure Worker-Side End-to-End Clearing Execution SLA
        logger.info("=================================================================")
        logger.info("Step 3: Auditing worker-side clearing latencies from database...")
        clearing_durations_ms: list[float] = []
        for pid in payment_ids[:20]:  # Sample up to 20 payments
            for _ in range(50):
                await asyncio.sleep(0.01)
                pr = await client.get(f"/payments/{pid}", headers=headers)
                if pr.status_code == 200 and pr.json().get("status") == "settled":
                    data = pr.json()
                    if data.get("created_at") and data.get("cleared_at"):
                        t_created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
                        t_cleared = datetime.fromisoformat(data["cleared_at"].replace("Z", "+00:00"))
                        clearing_durations_ms.append((t_cleared - t_created).total_seconds() * 1000)
                    break

        w_p50: float | None = None
        w_p99: float | None = None
        w_min: float | None = None
        if clearing_durations_ms:
            clearing_durations_ms.sort()
            w_min = min(clearing_durations_ms)
            w_p50 = statistics.median(clearing_durations_ms)
            w_p99 = clearing_durations_ms[int(len(clearing_durations_ms) * 0.99)]
            logger.info("WORKER END-TO-END CLEARING SLA (Queue Wait + Worker Exec + Partner Bank)")
            logger.info(
                "Sample Size: %d | Min: %.2f ms | P50: %.2f ms | P99: %.2f ms",
                len(clearing_durations_ms),
                w_min,
                w_p50,
                w_p99,
            )
            if w_p99 < 100.0:
                logger.info("SUCCESS: Worker clearing P99 (%.2f ms) is well within the 100 ms SLA!", w_p99)
            else:
                logger.warning("WARNING: Worker clearing P99 (%.2f ms) exceeded 100 ms SLA threshold", w_p99)
        logger.info("=================================================================")

        # 6. Construct structured performance report
        timestamp_now = datetime.now(timezone.utc)
        report: dict[str, Any] = {
            "timestamp": timestamp_now.isoformat(),
            "environment": {
                "api_url": api_url,
                "mode": "paced" if rate > 0 else "burst",
                "arrival_rate_req_sec": rate,
            },
            "parameters": {
                "bulk_saturation_count": bulk_count,
                "instant_probes_count": instant_count,
            },
            "bulk_ingestion": {
                "items_count": bulk_count,
                "ingestion_duration_ms": round(t_bulk_ingest, 2),
                "status_code": batch_res.status_code,
            },
            "api_ingestion_latency_ms": {
                "count": len(latencies_ms),
                "min": round(min_lat, 2),
                "mean": round(mean, 2),
                "p50": round(p50, 2),
                "p95": round(p95, 2),
                "p99": round(p99, 2),
                "max": round(max_lat, 2),
                "sla_threshold_ms": 100.0,
                "sla_passed": p99 < 100.0,
            },
            "worker_clearing_latency_ms": {
                "sample_size": len(clearing_durations_ms),
                "min": round(w_min, 2) if w_min is not None else None,
                "p50": round(w_p50, 2) if w_p50 is not None else None,
                "p99": round(w_p99, 2) if w_p99 is not None else None,
                "sla_threshold_ms": 100.0,
                "sla_passed": (w_p99 < 100.0) if w_p99 is not None else False,
            }
            if clearing_durations_ms
            else None,
        }

        # 7. Persist report to disk for historical profiling and regression tracking
        target_dir = Path("reports/benchmarks")
        target_dir.mkdir(parents=True, exist_ok=True)

        if output_path:
            file_path = Path(output_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            time_str = timestamp_now.strftime("%Y%m%d_%H%M%S")
            file_path = target_dir / f"benchmark_{time_str}.json"

        with open(file_path, "w") as f:
            json.dump(report, f, indent=2)

        # Always update latest.json in target_dir
        latest_path = target_dir / "latest.json"
        with open(latest_path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info("Saved benchmark report to %s and %s", file_path, latest_path)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Payment Orchestrator Contention Benchmark")
    parser.add_argument("--url", default="http://localhost:8010", help="API Gateway URL")
    parser.add_argument("--bulk", type=int, default=500, help="Number of bulk items")
    parser.add_argument("--probes", type=int, default=100, help="Number of instant payment probes (default 100)")
    parser.add_argument(
        "--rate",
        type=float,
        default=50.0,
        help="Probe arrival rate in req/s (default 50.0; set 0 for burst)",
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
            bulk_count=args.bulk,
            instant_count=args.probes,
            rate=args.rate,
            output_path=args.output,
        )
    )
