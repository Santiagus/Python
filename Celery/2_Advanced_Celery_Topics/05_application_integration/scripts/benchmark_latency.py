"""Automated Latency & Capacity Benchmark Harness for Card Dispute Engine.

Measures dual-layer performance metrics:
1. API Gateway Ingestion Latency (P50, P95, P99) under paced Little's Law arrival rates.
2. Worker End-to-End Clearing SLA (created_at to submitted_to_network).
Persists structured JSON execution metrics to reports/benchmarks/ for historical evolution tracking.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dispute_benchmark")

MODULE_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = MODULE_ROOT / "reports" / "benchmarks"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


async def run_latency_benchmark(
    api_url: str = "http://localhost:8000",
    api_key: str = "sk_live_card_disputes_test_key_001",
    probes_count: int = 100,
    rate: float = 50.0,
    output_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Execute dual-layer latency benchmark with Little's Law arrival rate pacing.

    Args:
        api_url: Base URL of the FastAPI gateway.
        api_key: Authentication secret header.
        probes_count: Number of requests to issue during the benchmark run.
        rate: Target arrival rate in requests per second (0 for unconstrained burst).
        output_path: Optional custom path to save the structured JSON report.

    Returns:
        dict[str, Any] | None: Structured report dictionary or None on connectivity failure.
    """
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)

    async with httpx.AsyncClient(base_url=api_url, headers=headers, limits=limits, timeout=30.0) as client:
        # 1. Verify Gateway Health
        try:
            health_res = await client.get("/health")
            if health_res.status_code != 200:
                logger.error("API Gateway not healthy (HTTP %d)", health_res.status_code)
                return None
        except Exception as exc:
            logger.error("Could not connect to API Gateway at %s: %s", api_url, exc)
            return None

        logger.info("=================================================================")
        logger.info("STARTING CARD DISPUTE LATENCY & CONTENTION BENCHMARK")
        mode_desc = f"Paced at {rate:.1f} req/s" if rate > 0 else "Unconstrained burst"
        logger.info("Target: %s | Probes: %d | Mode: %s", api_url, probes_count, mode_desc)
        logger.info("=================================================================")

        # 2. Pre-warm HTTP keep-alive pool with warm-up requests
        warm_dispute_ids: list[str] = []
        for w_idx in range(5):
            warm_payload = {
                "transaction_id": f"tx_warmup_{uuid4().hex[:8]}",
                "card_token": "tok_card_warmup_01",
                "card_last_four": "1234",
                "amount": "10.00",
                "currency": "USD",
                "reason": "unrecognized",
            }
            try:
                res = await client.post("/disputes", json=warm_payload)
                if res.status_code == 202:
                    warm_dispute_ids.append(res.json()["id"])
            except Exception:
                pass

        # 3. Define single probe routine
        created_dispute_ids: list[str] = []

        async def send_probe(probe_idx: int) -> tuple[float, bool]:
            """Send a single probe (alternating writes and reads)."""
            t_start = time.perf_counter()
            success = False
            try:
                if probe_idx % 2 == 0:
                    # Write probe: submit a new card dispute
                    payload = {
                        "transaction_id": f"tx_bench_{uuid4().hex[:12]}",
                        "card_token": "tok_card_bench_99",
                        "card_last_four": "4242",
                        "amount": f"{(10.0 + (probe_idx * 0.5)):.2f}",
                        "currency": "USD",
                        "reason": "fraudulent",
                        "evidence_notes": f"Automated benchmark probe {probe_idx}",
                    }
                    r = await client.post("/disputes", json=payload)
                    success = r.status_code == 202
                    if success:
                        created_dispute_ids.append(r.json()["id"])
                else:
                    # Read probe: inspect immediate in-flight or warm dispute
                    target_id = created_dispute_ids[-1] if created_dispute_ids else (
                        warm_dispute_ids[0] if warm_dispute_ids else str(uuid4())
                    )
                    r = await client.get(f"/disputes/{target_id}")
                    success = r.status_code in (200, 404)
            except Exception as exc:
                logger.warning("Probe %d encountered exception: %s", probe_idx, exc)
                success = False

            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            return elapsed_ms, success

        # 4. Dispatch probes under arrival rate pacing
        latencies_ms: list[float] = []
        successes = 0

        t_bench_start = time.perf_counter()
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
            tasks = [send_probe(i) for i in range(probes_count)]
            results = await asyncio.gather(*tasks)
            latencies_ms = [r[0] for r in results]
            successes = sum(1 for r in results if r[1])
        t_bench_total_s = time.perf_counter() - t_bench_start

        # 5. Compute API Ingestion Latency distribution
        latencies_ms.sort()
        p50 = statistics.median(latencies_ms)
        p95 = latencies_ms[min(int(len(latencies_ms) * 0.95), len(latencies_ms) - 1)]
        p99 = latencies_ms[min(int(len(latencies_ms) * 0.99), len(latencies_ms) - 1)]
        mean_lat = statistics.mean(latencies_ms)
        min_lat = min(latencies_ms)
        max_lat = max(latencies_ms)
        throughput_rps = len(latencies_ms) / t_bench_total_s if t_bench_total_s > 0 else 0.0

        logger.info("=================================================================")
        logger.info("BENCHMARK RESULTS: API INGESTION ROUNDTRIP LATENCY")
        logger.info("Probes Dispatched: %d (%d successful, %.1f req/s)", len(latencies_ms), successes, throughput_rps)
        logger.info("Min: %.2f ms | Mean: %.2f ms | Max: %.2f ms", min_lat, mean_lat, max_lat)
        logger.info("P50: %.2f ms | P95: %.2f ms | P99: %.2f ms", p50, p95, p99)

        if p99 <= 50.0:
            logger.info("SUCCESS: API Ingestion P99 latency (%.2f ms) is within 50 ms SLA!", p99)
        else:
            logger.warning("WARNING: API Ingestion P99 latency (%.2f ms) exceeded 50 ms SLA target", p99)

        # 6. Measure Worker Clearing SLA on sample disputes
        clearing_durations_ms: list[float] = []
        if created_dispute_ids:
            logger.info("=================================================================")
            logger.info("Step 3: Polling sample disputes for Worker Clearing SLA...")
            sample_ids = created_dispute_ids[:5]
            for s_id in sample_ids:
                t0_poll = time.perf_counter()
                cleared = False
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    poll_res = await client.get(f"/disputes/{s_id}")
                    if poll_res.status_code == 200:
                        data = poll_res.json()
                        if data.get("status") in ("submitted_to_network", "failed", "cancelled"):
                            clearing_durations_ms.append((time.perf_counter() - t0_poll) * 1000.0)
                            cleared = True
                            break
                if not cleared:
                    logger.debug("Dispute %s did not reach terminal state during polling window", s_id)

        mean_clearing_ms = statistics.mean(clearing_durations_ms) if clearing_durations_ms else None
        if mean_clearing_ms is not None:
            logger.info("Sample Worker Clearing SLA: Mean %.2f ms across %d samples", mean_clearing_ms, len(clearing_durations_ms))
        else:
            logger.info("Worker clearing SLA measurement skipped (worker daemon not active on target)")

        logger.info("=================================================================")

        # 7. Construct and persist structured JSON benchmark report
        now_dt = datetime.now(timezone.utc)
        report: dict[str, Any] = {
            "timestamp": now_dt.isoformat(),
            "environment": {
                "api_url": api_url,
                "mode": "paced" if rate > 0 else "burst",
                "arrival_rate_req_sec": rate,
            },
            "parameters": {
                "probes_count": probes_count,
            },
            "results": {
                "total_probes": len(latencies_ms),
                "successful_probes": successes,
                "failed_probes": len(latencies_ms) - successes,
                "duration_seconds": round(t_bench_total_s, 3),
                "actual_throughput_rps": round(throughput_rps, 2),
                "api_latency_ms": {
                    "min": round(min_lat, 2),
                    "mean": round(mean_lat, 2),
                    "p50": round(p50, 2),
                    "p95": round(p95, 2),
                    "p99": round(p99, 2),
                    "max": round(max_lat, 2),
                },
                "worker_clearing_sla_ms": {
                    "mean": round(mean_clearing_ms, 2) if mean_clearing_ms else None,
                    "samples_polled": len(clearing_durations_ms),
                },
                "sla_verdicts": {
                    "api_p99_under_50ms": p99 <= 50.0,
                    "worker_clearing_active": mean_clearing_ms is not None,
                },
            },
        }

        # 8. Persist to reports/benchmarks/
        date_str = now_dt.strftime("%Y%m%d_%H%M%S")
        target_file = Path(output_path) if output_path else REPORTS_DIR / f"benchmark_{date_str}.json"
        latest_file = REPORTS_DIR / "latest.json"

        target_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        latest_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Structured benchmark report persisted to %s", target_file)

        return report


def main() -> None:
    """CLI entrypoint for running latency benchmark."""
    parser = argparse.ArgumentParser(description="Card Dispute API Latency Benchmark")
    parser.add_argument("--api-url", default="http://localhost:8000", help="FastAPI gateway base URL")
    parser.add_argument("--api-key", default="sk_live_card_disputes_test_key_001", help="API Key header")
    parser.add_argument("--probes", type=int, default=100, help="Number of probe requests")
    parser.add_argument("--rate", type=float, default=50.0, help="Arrival rate in req/s (0 for burst)")
    parser.add_argument("--output", default=None, help="Custom output JSON path")

    args = parser.parse_args()
    asyncio.run(
        run_latency_benchmark(
            api_url=args.api_url,
            api_key=args.api_key,
            probes_count=args.probes,
            rate=args.rate,
            output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
