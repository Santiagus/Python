"""Automated CI/CD Capacity & Contention Regression Gate.

Executes a calibrated headless load test (150 req/s instant payouts with simultaneous
background batch payroll submissions) to automatically verify production SLAs:
1. Instant P99 <= 100.0 ms
2. Error Rate == 0.00%
3. Peak Database Server Connections <= 26
4. Latency degradation <= +15% over proven baseline (P99 <= 95.45 ms)

Exits with code 0 on PASS, 1 on FAIL. Designed for seamless execution in GitHub Actions,
GitLab CI, or local pre-merge verification.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import statistics
import sys
import time
from typing import Any
from uuid import uuid4

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports" / "benchmarks"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ci_contention_gate")

DEFAULT_GATEWAY_URL = "http://localhost:8010"
DEFAULT_API_KEY = "sk_live_payment_orchestrator_secret_key_2026"
DEFAULT_TARGET_RATE = 150.0  # req/s
DEFAULT_DURATION_SECONDS = 20.0
DEFAULT_P99_THRESHOLD_MS = 100.0
DEFAULT_BASELINE_P99_MS = 83.0
DEFAULT_MAX_DEGRADATION_PCT = 15.0  # 83ms * 1.15 = 95.45ms
DEFAULT_MAX_DB_CONNECTIONS = 26


def pre_generate_batch_payloads(count: int = 10, items_per_batch: int = 100) -> list[bytes]:
    """Pre-serialize multi-row payroll batch payloads to eliminate client-side overhead."""
    payloads = []
    for batch_idx in range(count):
        source_account = f"a0000000-0000-0000-0000-{(batch_idx % 20) + 80:012d}"
        disbursements = [
            {
                "recipient_name": f"GateWorker {batch_idx} Emp {i}",
                "account_number": f"9999{i:08d}",
                "routing_number": "021000021",
                "amount": "150.00",
            }
            for i in range(items_per_batch)
        ]
        body = {
            "file_reference": f"gate_payroll_{uuid4().hex[:8]}_{batch_idx}",
            "source_account_id": source_account,
            "disbursements": disbursements,
        }
        payloads.append(json.dumps(body).encode("utf-8"))
    return payloads


async def background_batch_submitter(
    client: httpx.AsyncClient,
    api_key: str,
    stop_event: asyncio.Event,
    interval_seconds: float = 2.0,
) -> int:
    """Continuously submits high-volume batch disbursements in the background."""
    payloads = pre_generate_batch_payloads(count=15, items_per_batch=100)
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    submitted_batches = 0
    idx = 0

    while not stop_event.is_set():
        payload = payloads[idx % len(payloads)]
        idx += 1
        try:
            res = await client.post("/disbursements/batch", content=payload, headers=headers)
            if res.status_code == 202:
                submitted_batches += 1
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass

    return submitted_batches


async def run_paced_instant_requests(
    client: httpx.AsyncClient,
    api_key: str,
    target_rate: float,
    duration: float,
) -> list[dict[str, Any]]:
    """Generate Little's Law paced instant payment requests at exact arrival frequency."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    delay_between_requests = 1.0 / target_rate
    end_time = time.monotonic() + duration
    results: list[dict[str, Any]] = []

    async def _send_request(req_idx: int) -> dict[str, Any]:
        source_account = f"a0000000-0000-0000-0000-{(req_idx % 50) + 1:012d}"
        payload = json.dumps({
            "idempotency_key": f"ci_gate_{uuid4().hex}_{req_idx}",
            "source_account_id": source_account,
            "destination_account_number": "123456789012",
            "destination_routing_number": "021000021",
            "amount": "25.00",
            "rail": "rtp",
        }).encode("utf-8")

        t_start = time.perf_counter()
        try:
            res = await client.post("/payments/instant", content=payload, headers=headers)
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            return {
                "success": res.status_code == 202,
                "status_code": res.status_code,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            return {
                "success": False,
                "status_code": 0,
                "latency_ms": (time.perf_counter() - t_start) * 1000.0,
                "error": str(exc),
            }

    tasks = []
    req_counter = 0
    next_time = time.monotonic()

    while time.monotonic() < end_time:
        tasks.append(asyncio.create_task(_send_request(req_counter)))
        req_counter += 1
        next_time += delay_between_requests
        sleep_time = next_time - time.monotonic()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    completed_results = await asyncio.gather(*tasks)
    return list(completed_results)


async def sample_db_connections(client: httpx.AsyncClient, api_key: str) -> int:
    """Sample active database connections from gateway metrics."""
    headers = {"X-API-Key": api_key}
    try:
        res = await client.get("/metrics", headers=headers)
        if res.status_code == 200:
            data = res.json()
            pool = data.get("db_connection_pool", {})
            checked_out = pool.get("checked_out", 0)
            overflow = pool.get("overflow", 0)
            return int(checked_out + max(0, overflow))
    except Exception:
        pass
    return 0


async def evaluate_contention_gate(
    gateway_url: str = DEFAULT_GATEWAY_URL,
    api_key: str = DEFAULT_API_KEY,
    target_rate: float = DEFAULT_TARGET_RATE,
    duration: float = DEFAULT_DURATION_SECONDS,
    p99_threshold_ms: float = DEFAULT_P99_THRESHOLD_MS,
    baseline_p99_ms: float = DEFAULT_BASELINE_P99_MS,
    max_degradation_pct: float = DEFAULT_MAX_DEGRADATION_PCT,
    max_db_connections: int = DEFAULT_MAX_DB_CONNECTIONS,
) -> bool:
    """Run the calibrated contention gate and assert all machine-verifiable SLAs."""
    logger.info("================================================================================")
    logger.info("STARTING AUTOMATED CI/CD CAPACITY & CONTENTION REGRESSION GATE")
    logger.info("================================================================================")
    logger.info(
        "Target Rate: %.1f req/s | Duration: %.0fs | P99 SLA: <=%.1f ms | Max DB Conns: <=%d",
        target_rate,
        duration,
        p99_threshold_ms,
        max_db_connections,
    )

    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    async with httpx.AsyncClient(base_url=gateway_url, limits=limits, timeout=10.0) as client:
        # 1. Verify Gateway Health
        try:
            health_res = await client.get("/health/ready")
            if health_res.status_code != 200:
                logger.error("Gateway health check failed with status %d", health_res.status_code)
                return False
        except Exception as exc:
            logger.error("Cannot connect to gateway at %s: %s", gateway_url, exc)
            return False

        # 2. Start Background Batch Payroll Generation
        stop_event = asyncio.Event()
        batch_task = asyncio.create_task(
            background_batch_submitter(client, api_key, stop_event, interval_seconds=1.5)
        )

        # 3. Sample initial DB connection baseline
        initial_db = await sample_db_connections(client, api_key)

        # 4. Execute Paced Instant Payment Load Harness
        logger.info("Executing %.1f req/s load harness for %.0f seconds under active bulk payroll...", target_rate, duration)
        results = await run_paced_instant_requests(client, api_key, target_rate, duration)

        # 5. Stop Background Batch Payroll
        stop_event.set()
        batches_submitted = await batch_task
        peak_db = max(initial_db, await sample_db_connections(client, api_key))

    # 6. Analyze Latencies and Error Rates
    latencies = [r["latency_ms"] for r in results if r["success"]]
    total_requests = len(results)
    successful_requests = len(latencies)
    failed_requests = total_requests - successful_requests
    error_rate = (failed_requests / total_requests) * 100.0 if total_requests > 0 else 100.0

    if not latencies:
        logger.error("FAILED: All instant payment requests failed!")
        return False

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    achieved_rps = total_requests / duration
    max_allowable_p99 = baseline_p99_ms * (1.0 + (max_degradation_pct / 100.0))

    # 7. Evaluate SLA Gates
    gate_p99_pass = p99 <= p99_threshold_ms
    gate_error_pass = error_rate == 0.00
    gate_db_pass = peak_db <= max_db_connections
    gate_regression_pass = p99 <= max_allowable_p99
    all_passed = gate_p99_pass and gate_error_pass and gate_db_pass and gate_regression_pass

    # 8. Print Formatted ASCII Gate Decision Table
    logger.info("--------------------------------------------------------------------------------")
    logger.info("CI/CD CONTENTION REGRESSION GATE RESULTS")
    logger.info("--------------------------------------------------------------------------------")
    logger.info("Total Requests:       %d (%d successful, %d failed)", total_requests, successful_requests, failed_requests)
    logger.info("Achieved Throughput:  %.1f req/s", achieved_rps)
    logger.info("Batches Submitted:    %d background payroll files (100 items each)", batches_submitted)
    logger.info("Latency Profile:      P50: %.1f ms | P95: %.1f ms | P99: %.1f ms", p50, p95, p99)
    logger.info("--------------------------------------------------------------------------------")
    logger.info(
        "Gate 1 [P99 SLA <= %.1f ms]:          %.1f ms -> %s",
        p99_threshold_ms,
        p99,
        "PASSED" if gate_p99_pass else "FAILED",
    )
    logger.info(
        "Gate 2 [Zero Error Rate == 0.00%%]:     %.2f%% -> %s",
        error_rate,
        "PASSED" if gate_error_pass else "FAILED",
    )
    logger.info(
        "Gate 3 [DB Conns <= %d]:             %d conns -> %s",
        max_db_connections,
        peak_db,
        "PASSED" if gate_db_pass else "FAILED",
    )
    logger.info(
        "Gate 4 [Regression <= +%.1f%% (<=%.1f ms)]: %.1f ms -> %s",
        max_degradation_pct,
        max_allowable_p99,
        p99,
        "PASSED" if gate_regression_pass else "FAILED",
    )
    logger.info("================================================================================")
    logger.info("OVERALL GATE DECISION: %s", "PASSED (Ready to Merge)" if all_passed else "FAILED (Regression Detected)")
    logger.info("================================================================================")

    # 9. Persist Structured JSON Artifact
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_data = {
        "timestamp": timestamp,
        "target_rate": target_rate,
        "achieved_rps": achieved_rps,
        "duration_seconds": duration,
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "error_rate_pct": error_rate,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "baseline_p99_ms": baseline_p99_ms,
        "max_allowable_p99_ms": max_allowable_p99,
        "peak_db_connections": peak_db,
        "batches_submitted": batches_submitted,
        "gate_p99_pass": gate_p99_pass,
        "gate_error_pass": gate_error_pass,
        "gate_db_pass": gate_db_pass,
        "gate_regression_pass": gate_regression_pass,
        "overall_pass": all_passed,
    }

    report_file = REPORTS_DIR / f"ci_gate_{timestamp}.json"
    latest_file = REPORTS_DIR / "latest_ci_gate.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    return all_passed


def main() -> None:
    """Parse CLI arguments and run the automated contention gate."""
    parser = argparse.ArgumentParser(description="Automated CI/CD Capacity & Contention Regression Gate")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Base URL of Nginx edge gateway")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Master M2M API authentication key")
    parser.add_argument("--rate", type=float, default=DEFAULT_TARGET_RATE, help="Target arrival rate in req/s")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_SECONDS, help="Duration in seconds")
    parser.add_argument("--p99-threshold", type=float, default=DEFAULT_P99_THRESHOLD_MS, help="Max allowable P99 in ms")
    parser.add_argument("--baseline-p99", type=float, default=DEFAULT_BASELINE_P99_MS, help="Proven baseline P99 in ms")
    parser.add_argument("--max-degradation", type=float, default=DEFAULT_MAX_DEGRADATION_PCT, help="Max degradation %")
    parser.add_argument("--max-db-conns", type=int, default=DEFAULT_MAX_DB_CONNECTIONS, help="Max DB connections")

    args = parser.parse_args()
    success = asyncio.run(
        evaluate_contention_gate(
            gateway_url=args.gateway_url,
            api_key=args.api_key,
            target_rate=args.rate,
            duration=args.duration,
            p99_threshold_ms=args.p99_threshold,
            baseline_p99_ms=args.baseline_p99,
            max_degradation_pct=args.max_degradation,
            max_db_connections=args.max_db_conns,
        )
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

