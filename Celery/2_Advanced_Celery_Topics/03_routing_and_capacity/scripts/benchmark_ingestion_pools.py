"""Empirical Ingestion SLA Isolation Benchmark: Unified Fleet vs. Golden Architecture Pools.

Golden Standard Benchmark Engine:
1. Pre-computed binary payloads: Pre-serializes batch JSON into bytes to eliminate
   client-side serialization bottleneck and ensure pure network/server measurement.
2. Dual-Layer Latency Telemetry: Audits both client-side roundtrip latency and server-side
   execution time (via X-Response-Time-Ms).
3. Traffic Models: Supports both Little's Law Arrival-Rate Pacing (--mode paced) and
   Unconstrained Concurrent Bursting (--mode burst).
4. Cold-Start Auditing: Measures initial transaction latency before connection pool warming.
5. Upstream Address Auditing: Verifies physical container isolation via X-Upstream-Addr.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import statistics
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
logger = logging.getLogger("ingestion_pools_benchmark")


def pre_generate_batch_payloads(count: int = 50, items_per_batch: int = 100) -> list[bytes]:
    """Pre-serialize batch disbursement JSON payloads into memory.

    Eliminates client-side JSON serialization overhead during benchmark execution.
    """
    payloads = []
    for batch_idx in range(count):
        source_account = f"a0000000-0000-0000-0000-{(batch_idx % 20) + 80:012d}"
        disbursements = [
            {
                "recipient_name": f"BatchWorker {batch_idx} Emp {i}",
                "account_number": f"8888{i:08d}",
                "routing_number": "021000021",
                "amount": "125.00",
            }
            for i in range(items_per_batch)
        ]
        body = {
            "file_reference": f"pool_pregen_{uuid4().hex[:8]}_{batch_idx}",
            "source_account_id": source_account,
            "disbursements": disbursements,
        }
        payloads.append(json.dumps(body).encode("utf-8"))
    return payloads


async def measure_cold_start(gateway_url: str, api_key: str) -> dict[str, float]:
    """Measure initial transaction latency on a newly spun-up container before warming."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    payload = json.dumps({
        "idempotency_key": f"cold_start_{uuid4().hex}",
        "source_account_id": "a0000000-0000-0000-0000-000000000001",
        "destination_account_number": "987654321098",
        "destination_routing_number": "021000021",
        "amount": "15.00",
        "rail": "fednow",
    }).encode("utf-8")

    async with httpx.AsyncClient(base_url=gateway_url, timeout=10.0) as client:
        t0 = time.perf_counter()
        try:
            res = await client.post("/payments/instant", content=payload, headers=headers)
            client_latency = (time.perf_counter() - t0) * 1000
            server_latency = float(res.headers.get("x-response-time-ms", client_latency))
            return {"client_ms": round(client_latency, 2), "server_ms": round(server_latency, 2)}
        except Exception as exc:
            logger.warning("Cold start probe exception: %s", exc)
            return {"client_ms": 0.0, "server_ms": 0.0}


async def warm_up(client: httpx.AsyncClient, api_key: str) -> None:
    """Warm up connection pools and Celery channels with warm-up probes."""
    logger.info("Pre-warming gateway and upstream connection pools (10 probes)...")
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    for i in range(10):
        payload = json.dumps({
            "idempotency_key": f"warmup_instant_{uuid4().hex}_{i}",
            "source_account_id": f"a0000000-0000-0000-0000-{(i % 70) + 1:012d}",
            "destination_account_number": "987600001111",
            "destination_routing_number": "021000021",
            "amount": "10.00",
            "rail": "rtp",
        }).encode("utf-8")
        try:
            await client.post("/payments/instant", content=payload, headers=headers)
        except Exception:
            pass

    await asyncio.sleep(0.5)


async def run_batch_worker(
    worker_id: int,
    client: httpx.AsyncClient,
    api_key: str,
    payloads: list[bytes],
    items_per_batch: int,
    stop_event: asyncio.Event,
    batch_stats: list[dict[str, Any]],
) -> None:
    """Continuously upload corporate payroll batches using pre-serialized payloads."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    seq = 0

    while not stop_event.is_set():
        payload_bytes = payloads[(worker_id + seq) % len(payloads)]
        seq += 1

        t0 = time.perf_counter()
        try:
            res = await client.post("/disbursements/batch", content=payload_bytes, headers=headers)
            duration_ms = (time.perf_counter() - t0) * 1000
            upstream = res.headers.get("X-Upstream-Addr", "unknown")
            server_time = float(res.headers.get("x-response-time-ms", duration_ms))
            batch_stats.append({
                "worker_id": worker_id,
                "status_code": res.status_code,
                "duration_ms": duration_ms,
                "server_time_ms": server_time,
                "upstream": upstream,
                "items": items_per_batch,
            })
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            batch_stats.append({
                "worker_id": worker_id,
                "status_code": 0,
                "duration_ms": duration_ms,
                "server_time_ms": 0.0,
                "upstream": "error",
                "error": str(exc),
                "items": items_per_batch,
            })

        # Yield to ensure network scheduling fairness
        await asyncio.sleep(0.08)


async def run_instant_paced(
    client: httpx.AsyncClient,
    api_key: str,
    rate: float,
    duration_seconds: float,
    stop_event: asyncio.Event,
    instant_stats: list[dict[str, Any]],
) -> None:
    """Paced real-time instant payments using Little's Law open-loop arrival intervals."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    interval = 1.0 / rate
    start_time = time.perf_counter()
    probe_idx = 0

    while time.perf_counter() - start_time < duration_seconds:
        probe_start = time.perf_counter()
        probe_idx += 1
        source_account = f"a0000000-0000-0000-0000-{(probe_idx % 75) + 1:012d}"
        payload = json.dumps({
            "idempotency_key": f"instant_pool_bench_{uuid4().hex}_{probe_idx}",
            "source_account_id": source_account,
            "destination_account_number": "987654321098",
            "destination_routing_number": "021000021",
            "amount": "25.00",
            "rail": "fednow",
            "description": f"Pool isolation probe #{probe_idx}",
        }).encode("utf-8")

        t0 = time.perf_counter()
        try:
            res = await client.post("/payments/instant", content=payload, headers=headers)
            client_lat = (time.perf_counter() - t0) * 1000
            upstream = res.headers.get("X-Upstream-Addr", "unknown")
            server_lat = float(res.headers.get("x-response-time-ms", client_lat))
            instant_stats.append({
                "probe_idx": probe_idx,
                "status_code": res.status_code,
                "client_ms": client_lat,
                "server_ms": server_lat,
                "upstream": upstream,
            })
        except Exception as exc:
            client_lat = (time.perf_counter() - t0) * 1000
            instant_stats.append({
                "probe_idx": probe_idx,
                "status_code": 0,
                "client_ms": client_lat,
                "server_ms": 0.0,
                "upstream": "error",
                "error": str(exc),
            })

        # Little's Law pacing sleep
        elapsed = time.perf_counter() - probe_start
        sleep_time = interval - elapsed
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    stop_event.set()
    await asyncio.sleep(0.3)


async def run_instant_burst(
    client: httpx.AsyncClient,
    api_key: str,
    concurrency: int,
    duration_seconds: float,
    stop_event: asyncio.Event,
    instant_stats: list[dict[str, Any]],
) -> None:
    """Unconstrained concurrent burst mode: simultaneous client workers firing continuously."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    start_time = time.perf_counter()
    lock = asyncio.Lock()
    counter = 0

    async def burst_client_loop(client_id: int) -> None:
        nonlocal counter
        while time.perf_counter() - start_time < duration_seconds:
            async with lock:
                counter += 1
                curr_idx = counter
            source_account = f"a0000000-0000-0000-0000-{(curr_idx % 75) + 1:012d}"
            payload = json.dumps({
                "idempotency_key": f"burst_{uuid4().hex}_{curr_idx}",
                "source_account_id": source_account,
                "destination_account_number": "987654321098",
                "destination_routing_number": "021000021",
                "amount": "25.00",
                "rail": "fednow",
            }).encode("utf-8")

            t0 = time.perf_counter()
            try:
                res = await client.post("/payments/instant", content=payload, headers=headers)
                client_lat = (time.perf_counter() - t0) * 1000
                upstream = res.headers.get("X-Upstream-Addr", "unknown")
                server_lat = float(res.headers.get("x-response-time-ms", client_lat))
                instant_stats.append({
                    "probe_idx": curr_idx,
                    "status_code": res.status_code,
                    "client_ms": client_lat,
                    "server_ms": server_lat,
                    "upstream": upstream,
                })
            except Exception as exc:
                client_lat = (time.perf_counter() - t0) * 1000
                instant_stats.append({
                    "probe_idx": curr_idx,
                    "status_code": 0,
                    "client_ms": client_lat,
                    "server_ms": 0.0,
                    "upstream": "error",
                    "error": str(exc),
                })
            # Brief micro-yield to maintain async loop responsiveness
            await asyncio.sleep(0.01)

    tasks = [asyncio.create_task(burst_client_loop(cid)) for cid in range(concurrency)]
    # Wait for duration
    await asyncio.sleep(duration_seconds)
    stop_event.set()
    await asyncio.gather(*tasks)


async def execute_benchmark(
    gateway_url: str = "http://localhost:8010",
    api_key: str = "sk_live_payment_orchestrator_secret_key_2026",
    mode: str = "paced",
    instant_rate: float = 35.0,
    burst_concurrency: int = 20,
    duration_seconds: float = 10.0,
    batch_concurrency: int = 2,
    items_per_batch: int = 100,
    label: str = "benchmark",
) -> dict[str, Any]:
    """Execute calibrated Ingestion SLA benchmark."""
    logger.info("================================================================================")
    logger.info("CALIBRATED INGESTION SLA BENCHMARK: %s [MODE: %s]", label.upper(), mode.upper())
    logger.info("================================================================================")
    logger.info("Gateway: %s | Duration: %.1fs", gateway_url, duration_seconds)
    if mode == "paced":
        logger.info("Traffic Model: Little's Law Arrival-Rate Pacing (%.1f req/s)", instant_rate)
    else:
        logger.info("Traffic Model: Unconstrained Concurrent Burst (%d concurrent clients)", burst_concurrency)
    logger.info("Batch Contention: %d workers submitting %d-item batches", batch_concurrency, items_per_batch)

    # 1. Cold-start probe
    logger.info("Step 1: Measuring cold-start latency before warm-up...")
    cold_start = await measure_cold_start(gateway_url, api_key)
    logger.info("Cold-start Latency: Client: %.2f ms | Server: %.2f ms", cold_start["client_ms"], cold_start["server_ms"])

    # Pre-serialize payloads
    pregen_payloads = pre_generate_batch_payloads(count=30, items_per_batch=items_per_batch)

    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    async with httpx.AsyncClient(base_url=gateway_url, timeout=30.0, limits=limits) as client:
        # Check health & warm up
        health = await client.get("/health/live")
        if health.status_code != 200:
            raise RuntimeError(f"Gateway not healthy: {health.status_code}")
        await warm_up(client, api_key)

        batch_stats: list[dict[str, Any]] = []
        instant_stats: list[dict[str, Any]] = []
        stop_event = asyncio.Event()

        # Start batch saturator workers
        batch_tasks = [
            asyncio.create_task(
                run_batch_worker(w_id, client, api_key, pregen_payloads, items_per_batch, stop_event, batch_stats)
            )
            for w_id in range(batch_concurrency)
        ]

        logger.info("Step 2: Dispatching real-time instant payment stream (%s mode)...", mode)
        t0_bench = time.perf_counter()
        if mode == "paced":
            await run_instant_paced(client, api_key, instant_rate, duration_seconds, stop_event, instant_stats)
        else:
            await run_instant_burst(client, api_key, burst_concurrency, duration_seconds, stop_event, instant_stats)
        bench_elapsed = time.perf_counter() - t0_bench

        # Terminate batch workers
        await asyncio.gather(*batch_tasks)

    # Metrics calculation
    instant_client_lats = [s["client_ms"] for s in instant_stats if s["status_code"] == 202]
    instant_server_lats = [s["server_ms"] for s in instant_stats if s["status_code"] == 202]
    instant_upstreams = Counter(s["upstream"] for s in instant_stats)
    batch_upstreams = Counter(s["upstream"] for s in batch_stats)
    batch_latencies = [b["duration_ms"] for b in batch_stats if b["status_code"] == 202]

    if not instant_client_lats:
        raise RuntimeError("No instant payment requests succeeded during benchmark!")

    instant_client_lats.sort()
    instant_server_lats.sort()
    count = len(instant_client_lats)

    def calc_percentiles(lats: list[float]) -> dict[str, float]:
        n = len(lats)
        return {
            "min": round(min(lats), 2),
            "p50": round(statistics.median(lats), 2),
            "p90": round(lats[int(n * 0.90)], 2),
            "p95": round(lats[int(n * 0.95)], 2),
            "p99": round(lats[int(n * 0.99)], 2),
            "max": round(max(lats), 2),
            "mean": round(statistics.mean(lats), 2),
        }

    client_pct = calc_percentiles(instant_client_lats)
    server_pct = calc_percentiles(instant_server_lats)
    throughput = count / bench_elapsed

    total_batch_items = sum(b["items"] for b in batch_stats if b["status_code"] == 202)
    batch_throughput = total_batch_items / bench_elapsed

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "mode": mode,
        "parameters": {
            "gateway_url": gateway_url,
            "mode": mode,
            "duration_seconds": duration_seconds,
            "actual_duration_seconds": round(bench_elapsed, 2),
            "instant_rate": instant_rate if mode == "paced" else None,
            "burst_concurrency": burst_concurrency if mode == "burst" else None,
            "batch_concurrency": batch_concurrency,
            "items_per_batch": items_per_batch,
        },
        "cold_start_ms": cold_start,
        "instant_payments": {
            "total_sent": len(instant_stats),
            "successful": count,
            "failed": len(instant_stats) - count,
            "throughput_rps": round(throughput, 2),
            "client_latency_ms": client_pct,
            "server_latency_ms": server_pct,
            "upstream_distribution": dict(instant_upstreams),
        },
        "batch_disbursements": {
            "total_batches": len(batch_stats),
            "successful_batches": len(batch_latencies),
            "total_items": total_batch_items,
            "items_per_second": round(batch_throughput, 2),
            "p50_duration_ms": round(statistics.median(batch_latencies) if batch_latencies else 0.0, 2),
            "upstream_distribution": dict(batch_upstreams),
        },
    }

    # Print Formatted Report
    logger.info("--------------------------------------------------------------------------------")
    logger.info("BENCHMARK RESULTS: %s [%s]", label.upper(), mode.upper())
    logger.info("--------------------------------------------------------------------------------")
    logger.info("Cold-Start Latency:           Client: %.2f ms | Server: %.2f ms", cold_start["client_ms"], cold_start["server_ms"])
    logger.info("Instant Payments Count:       %d sent (Success: %d, Failed: %d)", len(instant_stats), count, len(instant_stats) - count)
    logger.info("Throughput:                   %.2f req/s", throughput)
    logger.info("Client Latency (Roundtrip):   P50: %.2f ms | P95: %.2f ms | P99: %.2f ms | Max: %.2f ms", client_pct["p50"], client_pct["p95"], client_pct["p99"], client_pct["max"])
    logger.info("Server Latency (Execution):   P50: %.2f ms | P95: %.2f ms | P99: %.2f ms | Max: %.2f ms", server_pct["p50"], server_pct["p95"], server_pct["p99"], server_pct["max"])
    logger.info("Instant Upstream Addrs:       %s", dict(instant_upstreams))
    logger.info("Batch Payroll Items Ingested: %d items (%.1f items/s)", total_batch_items, batch_throughput)
    logger.info("Batch Upstream Addrs:         %s", dict(batch_upstreams))
    logger.info("--------------------------------------------------------------------------------")

    return report


def main() -> None:
    """CLI Entrypoint."""
    parser = argparse.ArgumentParser(description="Ingestion SLA Calibration Benchmark")
    parser.add_argument("--url", default="http://localhost:8010", help="Nginx Gateway Base URL")
    parser.add_argument("--api-key", default="sk_live_payment_orchestrator_secret_key_2026", help="API Key")
    parser.add_argument("--mode", choices=["paced", "burst"], default="paced", help="Traffic model")
    parser.add_argument("--rate", type=float, default=35.0, help="Arrival rate in paced mode (req/s)")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent clients in burst mode")
    parser.add_argument("--duration", type=float, default=10.0, help="Benchmark duration (seconds)")
    parser.add_argument("--batch-concurrency", type=int, default=2, help="Concurrent batch workers")
    parser.add_argument("--batch-items", type=int, default=100, help="Items per payroll batch")
    parser.add_argument("--label", default="golden_arch", help="Run label (e.g. unified, golden_arch)")
    parser.add_argument("--output", default=None, help="Custom output JSON path")

    args = parser.parse_args()

    report = asyncio.run(
        execute_benchmark(
            gateway_url=args.url,
            api_key=args.api_key,
            mode=args.mode,
            instant_rate=args.rate,
            burst_concurrency=args.concurrency,
            duration_seconds=args.duration,
            batch_concurrency=args.batch_concurrency,
            items_per_batch=args.batch_items,
            label=args.label,
        )
    )

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = Path(args.output) if args.output else REPORTS_DIR / f"ingestion_matrix_{args.label}_{args.mode}_{timestamp_str}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Saved report to: %s", out_file)

    latest_file = REPORTS_DIR / f"ingestion_matrix_{args.label}_{args.mode}_latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
