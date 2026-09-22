"""Automated Multi-Dimensional Capacity Matrix Benchmarking Engine.

Orchestrates Locust load testing across varying API Gateway container replica scales (C in [1, 2, 4, 8]),
batch slicing chunk sizes (N in [50, 100, 250]), and Celery token-bucket rate limits ('500/m', '3000/m', 'None').
Audits PostgreSQL connection usage via pg_stat_activity, measures tail latency (P50/P95/P99),
records throughput (RPS), and synthesizes the empirical Pareto-optimal system configuration.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("capacity_matrix")

# Database connection pool budget by container scale (each container running 1 worker)
SIZING_BUDGETS: dict[int, dict[str, int]] = {
    1: {"pool": 15, "overflow": 15, "max_gw_demand": 30},
    2: {"pool": 10, "overflow": 10, "max_gw_demand": 40},
    4: {"pool": 7, "overflow": 5, "max_gw_demand": 48},
    6: {"pool": 5, "overflow": 4, "max_gw_demand": 54},
    8: {"pool": 4, "overflow": 3, "max_gw_demand": 56},
}

CELERY_FIXED_DEMAND = 32  # 8 Celery worker processes * 4 max connections
POSTGRES_MAX_LIMIT = 100


def measure_cold_start_latency(api_url: str, api_key: str = "sk_live_payment_orchestrator_secret_key_2026") -> float:
    """Measure first-transaction latency on a newly spun-up or scaled API container.

    Captures initial socket handshakes, asyncpg pool initialization, and Kombu AMQP channel dial.

    Args:
        api_url: Base URL of the API gateway (via Nginx reverse proxy).
        api_key: M2M authentication key.

    Returns:
        float: Cold-start latency in milliseconds.
    """
    from uuid import uuid4
    payment_ref = uuid4().hex
    payload = json.dumps({
        "idempotency_key": f"cold_start_{payment_ref}",
        "source_account_id": "a0000000-0000-0000-0000-000000000001",
        "destination_account_number": "987612345678",
        "destination_routing_number": "021000021",
        "amount": "15.00",
        "rail": "fednow",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/payments/instant",
        data=payload,
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 202:
                return round((time.perf_counter() - t0) * 1000, 2)
    except Exception as exc:
        logger.warning("Cold start probe error: %s", exc)
    return round((time.perf_counter() - t0) * 1000, 2)


def warm_up_api(api_url: str, count: int = 20, api_key: str = "sk_live_payment_orchestrator_secret_key_2026") -> None:
    """Send warm-up probes to prime Nginx keepalive, asyncpg connections, and Celery AMQP channels.

    Args:
        api_url: Base URL of the API gateway.
        count: Number of pre-warm probes to dispatch.
        api_key: M2M authentication key.
    """
    from uuid import uuid4
    logger.info("Pre-warming API gateway (%d probes to prime connection pools)...", count)
    for i in range(count):
        payment_ref = uuid4().hex
        payload = json.dumps({
            "idempotency_key": f"warmup_{payment_ref}_{i}",
            "source_account_id": f"a0000000-0000-0000-0000-{(i % 100) + 1:012d}",
            "destination_account_number": "987600001111",
            "destination_routing_number": "021000021",
            "amount": "10.00",
            "rail": "rtp",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{api_url.rstrip('/')}/payments/instant",
            data=payload,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0):
                pass
        except Exception:
            pass
    # Brief pause to allow Celery workers to clear warm-up probes
    time.sleep(0.5)


def wait_for_api_healthy(api_url: str, timeout_seconds: float = 15.0) -> bool:
    """Poll the API health endpoint until healthy or timeout expires.

    Args:
        api_url: Base URL of the API gateway (via Nginx reverse proxy).
        timeout_seconds: Maximum seconds to wait.

    Returns:
        bool: True if alive and healthy, False if timed out.
    """
    health_url = f"{api_url.rstrip('/')}/health/live"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def query_postgres_connections() -> tuple[int, int]:
    """Query live PostgreSQL total and active connections via docker exec.

    Returns:
        tuple[int, int]: (total_connections, active_connections).
    """
    try:
        sql = (
            "SELECT count(*), count(*) FILTER (WHERE state = 'active') "
            "FROM pg_stat_activity WHERE datname = 'payments_db';"
        )
        res = subprocess.run(
            [
                "docker",
                "exec",
                "payment_postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                "payments_db",
                "-t",
                "-A",
                "-F",
                ",",
                "-c",
                sql,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        parts = res.stdout.strip().split(",")
        total = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
        active = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return total, active
    except Exception as e:
        logger.warning("Could not query pg_stat_activity: %s", e)
        return 0, 0


def configure_api_scale(replicas: int, pool: int, overflow: int, chunk_size: int = 100) -> bool:
    """Dynamically reconfigure and scale the API gateway container fleet.

    Args:
        replicas: Number of API container replicas.
        pool: DB_POOL_SIZE per container.
        overflow: DB_MAX_OVERFLOW per container.
        chunk_size: BATCH_CHUNK_SIZE setting.

    Returns:
        bool: True if successful, False otherwise.
    """
    env = os.environ.copy()
    env["API_INSTANT_DB_POOL_SIZE"] = str(pool)
    env["API_INSTANT_DB_MAX_OVERFLOW"] = str(overflow)
    env["API_DB_POOL_SIZE"] = str(pool)
    env["API_DB_MAX_OVERFLOW"] = str(overflow)
    env["BATCH_CHUNK_SIZE"] = str(chunk_size)
    env["RATE_LIMIT_RPM"] = "60000"

    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--scale", f"api_instant={replicas}"],
            env=env,
            check=True,
            capture_output=True,
        )
        # Reload Nginx to ensure upstream DNS and keepalive pool refresh
        subprocess.run(
            ["docker", "exec", "payment_gateway", "nginx", "-s", "reload"],
            check=False,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to scale API container fleet to %d: %s", replicas, e.stderr)
        return False


def set_celery_bulk_rate_limit(rate_limit: str | None) -> None:
    """Broadcast dynamic token-bucket rate limit to Celery bulk worker fleet via AMQP.

    Args:
        rate_limit: Rate limit string (e.g. '500/m', '3000/m', 'None').
    """
    val = "0" if not rate_limit or rate_limit.lower() in ("none", "0", "unconstrained") else rate_limit
    try:
        from services.worker.celery_app import celery_app
        res = celery_app.control.rate_limit(
            "services.worker.tasks.settlements.process_payroll_chunk",
            rate_limit=val,
            reply=True,
        )
        logger.info("Broadcast dynamic Celery rate limit '%s': %s", val, res)
    except Exception as exc:
        logger.warning("Could not broadcast dynamic Celery rate limit via AMQP: %s", exc)


def parse_locust_csv(csv_prefix: Path) -> dict[str, Any]:
    """Parse output CSV files generated by Locust.

    Args:
        csv_prefix: Path prefix used for Locust CSV exports.

    Returns:
        dict[str, Any]: Extracted metrics for instant payments and aggregated traffic.
    """
    stats_file = csv_prefix.with_name(f"{csv_prefix.name}_stats.csv")
    results: dict[str, Any] = {
        "aggregated": {},
        "instant_payment": {},
    }

    if not stats_file.exists():
        logger.error("Locust stats file not found: %s", stats_file)
        return results

    try:
        with open(stats_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Name", "")
                metric_entry = {
                    "request_count": int(row.get("Request Count", 0)),
                    "failure_count": int(row.get("Failure Count", 0)),
                    "median_response_time": float(row.get("Median Response Time", 0)),
                    "avg_response_time": float(row.get("Average Response Time", 0)),
                    "min_response_time": float(row.get("Min Response Time", 0)),
                    "max_response_time": float(row.get("Max Response Time", 0)),
                    "requests_per_sec": float(row.get("Requests/s", 0)),
                    "failures_per_sec": float(row.get("Failures/s", 0)),
                    "p50": float(row.get("50%", 0)),
                    "p90": float(row.get("90%", 0)),
                    "p95": float(row.get("95%", 0)),
                    "p99": float(row.get("99%", 0)),
                }
                if name == "Aggregated":
                    results["aggregated"] = metric_entry
                elif "/payments/instant" in name:
                    results["instant_payment"] = metric_entry
    except Exception as e:
        logger.error("Failed to parse Locust CSV: %s", e)

    return results


def run_benchmark_for_profile(
    replicas: int,
    chunk_size: int,
    rate_limit: str,
    users: int,
    spawn_rate: int,
    duration_str: str,
    arrival_rate: float,
    api_url: str,
    scratch_dir: Path,
) -> dict[str, Any]:
    """Execute load test scenario for a specific configuration profile.

    Args:
        replicas: API container replica scale to test.
        chunk_size: Batch disbursement slicing chunk size.
        rate_limit: Celery bulk queue token bucket rate limit.
        users: Number of Locust concurrent users.
        spawn_rate: User spawn rate per second.
        duration_str: Test duration (e.g. '15s').
        arrival_rate: Target aggregate arrival rate in req/s for Little's Law pacing.
        api_url: Base API gateway URL (via Nginx reverse proxy).
        scratch_dir: Working directory for temporary test artifacts.

    Returns:
        dict[str, Any]: Benchmark results dictionary.
    """
    budget = SIZING_BUDGETS.get(replicas, {"pool": 7, "overflow": 5, "max_gw_demand": replicas * 12})
    logger.info("-----------------------------------------------------------------")
    logger.info(
        "TESTING PROFILE: Replicas=%d | ChunkSize=%d | RateLimit=%s | Users=%d | Rate=%.1f req/s",
        replicas,
        chunk_size,
        rate_limit,
        users,
        arrival_rate,
    )

    # 1. Scale container fleet
    t0 = time.time()
    if not configure_api_scale(replicas, budget["pool"], budget["overflow"], chunk_size):
        raise RuntimeError(f"Could not scale API containers to {replicas} replicas")

    # 2. Update dynamic Celery rate limit via AMQP
    set_celery_bulk_rate_limit(rate_limit)

    # 3. Wait for API healthy
    if not wait_for_api_healthy(api_url, timeout_seconds=30.0):
        raise RuntimeError(f"API failed to become healthy at {replicas} replicas")
    logger.info("API healthy with %d replicas in %.2fs", replicas, time.time() - t0)

    # 3a. Measure cold-start latency on fresh container
    cold_start_ms = measure_cold_start_latency(api_url)
    logger.info("Measured Cold-Start Ingestion Latency: %.2f ms", cold_start_ms)

    # 3b. Pre-warm API gateway (priming Nginx keepalive, asyncpg pool, Kombu channel)
    warm_up_api(api_url, count=20)

    # 4. Audit initial DB connections
    db_total_before, db_active_before = query_postgres_connections()

    # 5. Run Locust
    # 5. Run Locust with Little's Law arrival rate pacing
    csv_prefix = scratch_dir / f"locust_r{replicas}_c{chunk_size}_{int(time.time())}"
    locust_cmd = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        "scripts/locustfile.py",
        "--headless",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "-t",
        duration_str,
        "--host",
        api_url,
        f"--csv={csv_prefix}",
    ]

    locust_env = os.environ.copy()
    if arrival_rate > 0:
        locust_env["LOCUST_ARRIVAL_RATE"] = str(arrival_rate)

    logger.info("Running Locust (%d users, %s duration, %.1f req/s pace)...", users, duration_str, arrival_rate)
    loc_proc = subprocess.run(locust_cmd, env=locust_env, check=False, capture_output=True, text=True)
    if loc_proc.returncode != 0:
        logger.warning(
            "Locust completed with exit code %d (failures observed): %s",
            loc_proc.returncode,
            loc_proc.stderr[-300:] if loc_proc.stderr else "no stderr",
        )

    # 6. Audit peak DB connections post-test
    db_total_after, db_active_after = query_postgres_connections()

    # 7. Parse results
    parsed_metrics = parse_locust_csv(csv_prefix)

    # 8. Cleanup temporary CSVs
    for p in scratch_dir.glob(f"{csv_prefix.name}*"):
        try:
            p.unlink()
        except OSError:
            pass

    max_system_demand = budget["max_gw_demand"] + CELERY_FIXED_DEMAND
    headroom_pct = round(((POSTGRES_MAX_LIMIT - max_system_demand) / POSTGRES_MAX_LIMIT) * 100, 1)

    return {
        "replicas": replicas,
        "chunk_size": chunk_size,
        "rate_limit": rate_limit,
        "cold_start_ms": cold_start_ms,
        "db_pool_budget": budget["pool"],
        "db_overflow_budget": budget["overflow"],
        "max_gateway_db_demand": budget["max_gw_demand"],
        "celery_db_demand": CELERY_FIXED_DEMAND,
        "total_max_db_demand": max_system_demand,
        "db_headroom_percent": headroom_pct,
        "measured_db_connections_peak": db_total_after,
        "aggregated": parsed_metrics.get("aggregated", {}),
        "instant_payment": parsed_metrics.get("instant_payment", {}),
    }


def identify_pareto_frontier(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Identify the Pareto-optimal configuration balancing throughput, latency, and database safety.

    Args:
        results: List of execution profiles.

    Returns:
        dict[str, Any] | None: Optimal configuration summary.
    """
    valid = [r for r in results if r.get("instant_payment", {}).get("request_count", 0) > 0]
    if not valid:
        return None

    # Filter candidates that satisfy the sub-100ms P99 SLA target
    sla_passing = [r for r in valid if r.get("instant_payment", {}).get("p99", 999.0) <= 100.0]
    eval_pool = sla_passing if sla_passing else valid

    # Score formula: Throughput / (P99 latency * (1 + failure_rate) * (1 + risk_penalty))
    best_candidate = None
    highest_score = -1.0

    for r in eval_pool:
        inst = r["instant_payment"]
        agg = r.get("aggregated", {})
        rps = agg.get("requests_per_sec", 0.0)
        p99 = max(inst.get("p99", 1.0), 1.0)
        failures = agg.get("failure_count", 0)
        total_reqs = max(agg.get("request_count", 1), 1)
        fail_rate = failures / total_reqs
        headroom = r.get("db_headroom_percent", 0.0)
        # Risk penalty if database headroom is less than 15%
        penalty = 0.5 if headroom < 15.0 else 0.0
        score = rps / (p99 * (1.0 + fail_rate * 10.0) * (1.0 + penalty))

        if score > highest_score:
            highest_score = score
            best_candidate = r

    return best_candidate


def main() -> None:
    """CLI Entry point for capacity matrix benchmarking."""
    parser = argparse.ArgumentParser(description="Multi-Dimensional Capacity Matrix Runner")
    parser.add_argument("--replicas", type=str, default="2", help="Comma-separated container replica counts (default: '2'; use '1,2,4' for full matrix)")
    parser.add_argument("--chunk-sizes", type=str, default="100", help="Comma-separated chunk sizes (default: '100'; e.g. 50,100,250)")
    parser.add_argument("--rate-limits", type=str, default="500/m", help="Comma-separated Celery rate limits (default: '500/m'; e.g. 500/m,3000/m,None)")
    parser.add_argument("--rate", type=float, default=35.0, help="Aggregate arrival rate in req/s for Little's Law pacing (default: 35.0; set 0 for unconstrained)")
    parser.add_argument("--users", type=int, default=25, help="Number of concurrent Locust users (default: 25)")
    parser.add_argument("--spawn-rate", type=int, default=10, help="Locust user spawn rate per second (default: 10)")
    parser.add_argument("--duration", type=str, default="15s", help="Duration per profile (default: '15s')")
    parser.add_argument("--quick", action="store_true", help="Quick mode (10s duration, replicas 1, 2)")
    parser.add_argument("--api-url", type=str, default="http://localhost:8010", help="API gateway base URL (default: http://localhost:8010)")
    parser.add_argument("--output", type=str, default=None, help="Custom output JSON path")

    args = parser.parse_args()

    replica_scales = [int(w.strip()) for w in args.replicas.split(",") if w.strip().isdigit()]
    chunk_sizes = [int(c.strip()) for c in args.chunk_sizes.split(",") if c.strip().isdigit()]
    rate_limits = [r.strip() for r in args.rate_limits.split(",") if r.strip()]
    duration = "15s" if args.quick else args.duration
    users = 15 if args.quick else args.users
    arrival_rate = args.rate

    logger.info("=================================================================")
    logger.info("STARTING HORIZONTAL SCALING CAPACITY MATRIX BENCHMARK")
    logger.info("Hardware Target: AMD Ryzen 9 7900 (12 Cores / 24 Threads)")
    logger.info(
        "Replicas: %s | Chunks: %s | Rate Limits: %s | Users: %d | Duration: %s | Rate: %.1f req/s",
        replica_scales,
        chunk_sizes,
        rate_limits,
        users,
        duration,
        arrival_rate,
    )
    logger.info("=================================================================")

    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        scratch_dir = Path(temp_dir)
        try:
            for rep in replica_scales:
                for chunk in chunk_sizes:
                    for r_limit in rate_limits:
                        res = run_benchmark_for_profile(
                            replicas=rep,
                            chunk_size=chunk,
                            rate_limit=r_limit,
                            users=users,
                            spawn_rate=args.spawn_rate,
                            duration_str=duration,
                            arrival_rate=arrival_rate,
                            api_url=args.api_url,
                            scratch_dir=scratch_dir,
                        )
                        results.append(res)
        finally:
            # Always restore production reference state (2 container replicas)
            logger.info("Restoring API Gateway to production reference state (2 container replicas)...")
            configure_api_scale(2, 10, 10, 100)
            set_celery_bulk_rate_limit("500/m")
            wait_for_api_healthy(args.api_url, timeout_seconds=10.0)

    # Identify Pareto Frontier
    pareto_winner = identify_pareto_frontier(results)

    # Print Comparison Table
    print("\n" + "=" * 148)
    print("EMPIRICAL HORIZONTAL CAPACITY MATRIX: NGINX + FASTAPI ATOMIC CONTAINERS (AMD RYZEN 9 7900)")
    print("=" * 148)
    header = (
        f"{'Scale':<9} | {'Chunk':<6} | {'Rate Limit':<11} | {'Throughput':<12} | {'Cold (ms)':<10} | "
        f"{'P50 (ms)':<9} | {'P95 (ms)':<9} | {'P99 (ms)':<9} | {'Max DB':<10} | {'DB Meas':<10} | {'SLA Status'}"
    )
    print(header)
    print("-" * 148)

    for r in results:
        scale_str = f"C = {r['replicas']}"
        chunk_str = f"N={r['chunk_size']}"
        rate_str = r["rate_limit"]
        inst = r.get("instant_payment", {})
        agg = r.get("aggregated", {})
        rps = f"{agg.get('requests_per_sec', 0.0):.1f} req/s"
        cold_str = f"{r.get('cold_start_ms', 0.0):.1f}"
        p50 = f"{inst.get('p50', 0.0):.2f}"
        p95 = f"{inst.get('p95', 0.0):.2f}"
        p99 = f"{inst.get('p99', 0.0):.2f}"
        max_db = f"{r['total_max_db_demand']}/100"
        meas_db = f"{r['measured_db_connections_peak']} active"
        sla = "PASS (<=100ms)" if inst.get("p99", 0.0) <= 100.0 else "FAIL (>100ms)"
        winner_mark = (
            " ⭐ [Pareto Optimal]"
            if pareto_winner
            and pareto_winner["replicas"] == r["replicas"]
            and pareto_winner["chunk_size"] == r["chunk_size"]
            and pareto_winner["rate_limit"] == r["rate_limit"]
            else ""
        )
        print(
            f"{scale_str:<9} | {chunk_str:<6} | {rate_str:<11} | {rps:<12} | {cold_str:<10} | "
            f"{p50:<9} | {p95:<9} | {p99:<9} | {max_db:<10} | {meas_db:<10} | {sla}{winner_mark}"
        )

    print("=" * 148)
    if pareto_winner:
        print(f"\nPARETO OPTIMAL RECOMMENDATION:")
        print(f"  • Container Replicas:   {pareto_winner['replicas']} atomic containers (1 Uvicorn worker per container)")
        print(f"  • Batch Chunk Size:     {pareto_winner['chunk_size']} items per chunk")
        print(f"  • Celery Rate Limit:    {pareto_winner['rate_limit']}")
        print(f"  • Sustained Throughput: {pareto_winner['aggregated'].get('requests_per_sec', 0.0):.1f} req/s")
        print(f"  • Cold-Start Latency:   {pareto_winner.get('cold_start_ms', 0.0):.1f} ms")
        print(f"  • Instant P99 Latency:  {pareto_winner['instant_payment'].get('p99', 0.0):.2f} ms")
        print(f"  • Database Headroom:    {pareto_winner['db_headroom_percent']}% safe headroom ({pareto_winner['total_max_db_demand']}/100 max demand)")
        print(f"  • Celery Fleet Demand:  {CELERY_FIXED_DEMAND} connections across 8 worker child processes")

    # Persist report
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_data = {
        "timestamp": timestamp,
        "hardware": "AMD Ryzen 9 7900 (12 Cores / 24 Threads, 32GB RAM)",
        "locust_users": users,
        "duration_per_profile": duration,
        "arrival_rate_pacing": arrival_rate,
        "pareto_optimal": pareto_winner,
        "matrix": results,
    }

    out_file = Path(args.output) if args.output else REPO_ROOT / "reports" / "benchmarks" / f"capacity_matrix_{timestamp}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    latest_file = out_file.parent / "capacity_matrix_latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    logger.info("Saved capacity matrix report to %s and %s", out_file, latest_file)


if __name__ == "__main__":
    main()
