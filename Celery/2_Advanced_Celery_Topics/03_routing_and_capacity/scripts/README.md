# Operational & Benchmark Scripts Guide

This directory contains the operational, seeding, and capacity benchmarking harnesses for the **Multi-Rail Payment Orchestrator & Batch Settlement Engine**.

Every script is built according to senior engineering and distributed systems invariants:
1. **Zero-Parameter Turnkey Execution**: Every script can be executed with zero CLI arguments (`python scripts/<script_name>.py`) and will run cleanly using safe, pre-configured defaults against the live local Docker Compose environment.
2. **Standardized Argument Parsing (`argparse`)**: All scripts provide full CLI parameterization with `--help` documentation for custom tuning, durations, concurrency levels, and arrival rates.
3. **Structured JSON Telemetry Persistence**: All capacity and contention benchmarks automatically persist execution metrics to `reports/benchmarks/<benchmark_name>_<timestamp>.json` and update `<benchmark_name>_latest.json` for historical regression tracking.
4. **Environment Port Invariant**: All scripts interacting with the ingestion layer default to `http://localhost:8010` (the Nginx Edge Gateway host port), ensuring full routing through Semantic Edge Routing and upstream balancing pools.

---

## 1. Quick Reference & Verification Matrix

| Script | Purpose & Architectural Role | Zero-Param Command | Default Zero-Param Behavior |
| :--- | :--- | :--- | :--- |
| [`seed_data.py`](seed_data.py) | PostgreSQL account seeding | `python scripts/seed_data.py` | Seeds 100 enterprise accounts (`a0000000-0000-0000-0000-000000000001..100`) with \$10M balances. |
| [`test_nginx_least_conn.py`](test_nginx_least_conn.py) | Empirical Nginx balancing audit | `python scripts/test_nginx_least_conn.py` | Runs paced stream (20 reqs) and burst (30 reqs) against 2.0s contention on port 8010. |
| [`load_test_contention.py`](load_test_contention.py) | Queue contention & clearing SLA | `python scripts/load_test_contention.py` | Submits 500 bulk items, 100 instant probes at 50 req/s, verifies $< 100\text{ ms}$ SLA. |
| [`benchmark_ingestion_pools.py`](benchmark_ingestion_pools.py) | Ingestion SLA pool calibration | `python scripts/benchmark_ingestion_pools.py` | Runs 10s paced test at 35 req/s against background payroll uploads on port 8010. |
| [`benchmark_chunks.py`](benchmark_chunks.py) | Batch chunk sizing velocity | `python scripts/benchmark_chunks.py` | Benchmarks 2,000 disbursement items across $N \in [25, 50, 100, 250, 500]$ under `500/m` rate limit. |
| [`locustfile.py`](locustfile.py) | Multi-rail Locust traffic generator | `python scripts/locustfile.py` | Runs 10s headless Locust test with 10 users spawned at 5/s against `http://localhost:8010`. |
| [`benchmark_capacity_matrix.py`](benchmark_capacity_matrix.py) | Multi-dimensional scaling matrix | `python scripts/benchmark_capacity_matrix.py` | Runs baseline profile ($C=2, N=100, \text{Rate}=3000/\text{m}$) for 15s and restores gateway. |

---

## 2. Detailed Parameter Reference & Examples

### 1. `seed_data.py`
Seeds synthetic enterprise funding accounts into PostgreSQL so multi-client load testing engines (like Locust) have sufficient accounts with deterministic UUIDs and valid balances.

* **Zero-Param Execution**:
  ```bash
  python scripts/seed_data.py
  ```
  *Default*: Ensures 100 accounts exist (`1000000000000001` through `10000000000100`) without purging existing payments.

* **Parameters**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `--count` | `int` | `100` | Total number of enterprise accounts to seed. |
  | `--reset` | `flag` | `False` | Purges dependent tables (`disbursements`, `batch_settlements`, `payments`, `accounts`) before inserting. |

* **Custom Examples**:
  ```bash
  # Seed 500 accounts for massive concurrency testing
  python scripts/seed_data.py --count 500

  # Reset database and re-seed clean 100 accounts
  python scripts/seed_data.py --reset --count 100
  ```

---

### 2. `test_nginx_least_conn.py`
Empirically audits Nginx's `least_conn` upstream balancing directive by measuring traffic distribution while one API container is artificially held in-flight with a slow request. Proves that `least_conn` eliminates head-of-line blocking compared to round-robin.

* **Zero-Param Execution**:
  ```bash
  python scripts/test_nginx_least_conn.py
  ```
  *Default*: Discovers online upstreams via `http://localhost:8010`, executes Test 1 (20 paced probes) and Test 2 (30 burst probes) during an artificial 2,000 ms slow request, prints side-by-side comparison with round-robin, and updates `reports/benchmarks/nginx_least_conn_benchmark_latest.json`.

* **Parameters**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `--url` | `str` | `"http://localhost:8010"` | Target Nginx Edge Gateway base URL. |
  | `--delay-ms` | `int` | `2000` | Artificial slow contention duration in milliseconds. |
  | `--paced-count` | `int` | `20` | Number of sequential requests in paced arrival test (~33 req/s). |
  | `--burst-count` | `int` | `30` | Number of simultaneous connections in concurrent burst test. |
  | `--output-dir` | `Path` | `"reports/benchmarks"` | Destination directory for structured JSON reports. |

* **Custom Examples**:
  ```bash
  # Test with a 3-second hold and 50 burst requests
  python scripts/test_nginx_least_conn.py --delay-ms 3000 --burst-count 50

  # Target a staging gateway
  python scripts/test_nginx_least_conn.py --url http://staging-gateway:8010
  ```

---

### 3. `load_test_contention.py`
Saturates the Celery `bulk` queue with hundreds or thousands of corporate disbursement line items while firing paced instant payment probes to measure API ingestion latency and Celery worker clearing P99 SLA.

* **Zero-Param Execution**:
  ```bash
  python scripts/load_test_contention.py
  ```
  *Default*: Pre-warms Celery AMQP channels with 10 probes, submits 500 bulk items, dispatches 100 instant payout probes at 50 req/s, polls 20 payments for worker-side clearing SLA, and saves report to `reports/benchmarks/latest.json`.

* **Parameters**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `--url` | `str` | `"http://localhost:8010"` | Target API Gateway base URL. |
  | `--bulk` | `int` | `500` | Number of bulk disbursement items to ingest for background load. |
  | `--probes` | `int` | `100` | Number of instant payment probes to measure ingestion latency. |
  | `--rate` | `float` | `50.0` | Little's Law probe arrival rate in req/s (set `0` for unconstrained burst). |
  | `--api-key` | `str` | `sk_live_...` | Machine-to-machine authentication API key. |
  | `--output-dir` | `Path` | `"reports/benchmarks"` | Destination directory for JSON benchmark reports. |

* **Custom Examples**:
  ```bash
  # Heavy background queue load: 5,000 bulk items with 200 probes at 100 req/s
  python scripts/load_test_contention.py --bulk 5000 --probes 200 --rate 100

  # Unconstrained simultaneous burst
  python scripts/load_test_contention.py --bulk 1000 --probes 100 --rate 0
  ```

---

### 4. `benchmark_ingestion_pools.py`
Validates that physical container pool separation (`api_instant` vs. `api_batch`) eliminates event loop CPU contention during large batch payroll JSON parsing. Proves that real-time payment ingestion latency ($P_{99} < 100\text{ ms}$) is preserved regardless of background payroll uploads.

* **Zero-Param Execution**:
  ```bash
  python scripts/benchmark_ingestion_pools.py
  ```
  *Default*: Runs 10-second paced benchmark at 35 req/s with 2 concurrent batch worker threads uploading 100-item payroll files, verifies $100\%$ upstream address segregation, and saves report to `reports/benchmarks/ingestion_matrix_golden_arch_paced_latest.json`.

* **Parameters**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `--url` | `str` | `"http://localhost:8010"` | Target Nginx Edge Gateway URL. |
  | `--mode` | `choice` | `"paced"` | Traffic model: `"paced"` (Little's Law arrival rate) or `"burst"` (simultaneous). |
  | `--rate` | `float` | `35.0` | Target arrival rate in req/s (when `--mode paced`). |
  | `--concurrency` | `int` | `20` | Number of concurrent clients (when `--mode burst`). |
  | `--duration` | `float` | `10.0` | Benchmark duration in seconds. |
  | `--batch-concurrency`| `int` | `2` | Number of concurrent background batch upload workers. |
  | `--batch-items` | `int` | `100` | Line items per background payroll disbursement file. |
  | `--label` | `str` | `"golden_arch"` | Telemetry report identifier label. |
  | `--output` | `str` | `None` | Optional custom output JSON file path. |

* **Custom Examples**:
  ```bash
  # Little's Law paced test at 50 req/s for 30 seconds
  python scripts/benchmark_ingestion_pools.py --rate 50 --duration 30

  # High-concurrency burst mode
  python scripts/benchmark_ingestion_pools.py --mode burst --concurrency 30 --duration 15
  ```

---

### 5. `benchmark_chunks.py`
Benchmarks Celery batch clearing velocity and database lock contention across varying chunk sizes ($N \in [25, 50, 100, 250, 500]$) against Celery's token-bucket rate limiter.

* **Zero-Param Execution**:
  ```bash
  python scripts/benchmark_chunks.py
  ```
  *Default*: Purges bulk queue, broadcasts `500/m` rate limit, tests 2,000 disbursements across chunk sizes 25, 50, 100, 250, and 500, prints speedup table relative to $N=100$, and updates `reports/benchmarks/chunk_latest.json`.

* **Parameters**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `--batch-size` | `int` | `2000` | Total number of disbursements per trial. |
  | `--chunk-sizes`| `list[int]`| `25 50 100 250 500` | Space-separated list of chunk sizes to benchmark. |
  | `--rate-limit` | `str` | `"500/m"` | Celery token-bucket rate limit policy (e.g. `'500/m'`, `'3000/m'`, `'none'`). |
  | `--output-dir` | `Path` | `"reports/benchmarks"` | Destination directory for JSON benchmark report. |

* **Custom Examples**:
  ```bash
  # Test higher volume (5,000 items) on optimal chunk sizes with relaxed rate limit
  python scripts/benchmark_chunks.py --batch-size 5000 --chunk-sizes 100 250 500 --rate-limit 3000/m

  # Unconstrained rate limiter comparison
  python scripts/benchmark_chunks.py --batch-size 2000 --chunk-sizes 100 250 --rate-limit none
  ```

---

### 6. `locustfile.py`
High-performance Locust user profile simulating realistic production multi-rail payment traffic (90% instant payments, 10% batch disbursements, 10% queue metrics). Can be executed standalone via Python or using the Locust CLI.

* **Zero-Param Execution**:
  ```bash
  python scripts/locustfile.py
  ```
  *Default*: Runs headless Locust benchmark for 10 seconds with 10 simulated users spawned at 5/s targeting `http://localhost:8010`.

* **Parameters**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `--host` | `str` | `"http://localhost:8010"` | Target API Gateway base URL. |
  | `-u`, `--users` | `int` | `10` | Number of concurrent simulated users. |
  | `-r`, `--spawn-rate` | `int` | `5` | User ramp-up rate per second. |
  | `-t`, `--run-time` | `str` | `"10s"` | Benchmark duration (e.g. `'10s'`, `'1m'`). |
  | `--web` | `flag` | `False` | Launches interactive Locust Web UI on `http://localhost:8089`. |

* **Custom Examples**:
  ```bash
  # Run 50 concurrent users for 30 seconds headless
  python scripts/locustfile.py -u 50 -r 10 -t 30s

  # Launch the interactive web dashboard
  python scripts/locustfile.py --web
  ```

---

### 7. `benchmark_capacity_matrix.py`
Automated capacity matrix engine that dynamically scales API container replicas (`api_instant`), audits PostgreSQL connection pool headroom via `pg_stat_activity`, and computes the Pareto-optimal operating point.

* **Zero-Param Execution**:
  ```bash
  python scripts/benchmark_capacity_matrix.py
  ```
  *Default*: Tests baseline configuration ($C=2$ replicas, $N=100$ chunk size, `500/m` rate limit, 25 Locust users at 35 req/s pace for 15 seconds), prints the empirical matrix table, restores the gateway to its reference state (2 replicas), and updates `reports/benchmarks/capacity_matrix_latest.json`.

* **Parameters**:
  | Parameter | Type | Default | Description |
  | :--- | :--- | :--- | :--- |
  | `--replicas` | `str` | `"2"` | Comma-separated container replica scales (e.g. `'1,2,4'`). |
  | `--chunk-sizes` | `str` | `"100"` | Comma-separated batch chunk sizes (e.g. `'50,100,250'`). |
  | `--rate-limits` | `str` | `"500/m"` | Comma-separated Celery rate limits (e.g. `'500/m,3000/m,None'`). |
  | `--rate` | `float` | `35.0` | Little's Law aggregate arrival rate in req/s (`0` for unconstrained). |
  | `--users` | `int` | `25` | Number of concurrent Locust load users. |
  | `--spawn-rate` | `int` | `10` | User spawn rate per second. |
  | `--duration` | `str` | `"15s"` | Load duration per profile. |
  | `--quick` | `flag` | `False` | Quick mode (10s duration, replicas 1, 2). |
  | `--api-url` | `str` | `"http://localhost:8010"` | Base Nginx Edge Gateway URL. |
  | `--output` | `str` | `None` | Optional custom output JSON file path. |

* **Custom Examples**:
  ```bash
  # Full multi-dimensional matrix sweep across 1, 2, and 4 container replicas
  python scripts/benchmark_capacity_matrix.py --replicas 1,2,4 --chunk-sizes 50,100 --duration 20s

  # Quick sweep (10s per profile on replicas 1 and 2)
  python scripts/benchmark_capacity_matrix.py --quick
  ```

---

## 3. Environment & Prerequisites

To run any script:
1. **Activate the Virtual Environment**:
   ```bash
   source .venv/bin/activate
   ```
2. **Ensure the Docker Compose Stack is Online**:
   ```bash
   docker compose up -d
   ```
   Verify that `payment_gateway` is listening on port `8010`, and all worker and API containers report healthy via `docker compose ps`.

