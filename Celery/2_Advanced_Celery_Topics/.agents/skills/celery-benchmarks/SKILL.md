---
name: celery-benchmarks
description: >-
  Implement and run automated performance benchmarks, capacity stress tests, Little's Law
  arrival-rate pacing, and structured JSON metric persistence for Celery and FastAPI systems.
  Use this skill when authoring benchmark harnesses, analyzing throughput/latency SLA,
  measuring clearing rates, or tracking historical performance metrics.
---

# Continuous Benchmark Profiling & Capacity Testing

This skill guides the construction, execution, and metric persistence of capacity, load, and queue contention benchmarks across FastAPI ingestion gateways and Celery worker fleets.

---

## 1. Core Benchmarking Invariants

### A. Structured JSON Benchmark Persistence
* **Rule**: All capacity and contention benchmarks (e.g., `scripts/load_test_*.py`) must persist structured execution metrics to disk under:
  ```text
  reports/benchmarks/benchmark_<YYYYMMDD_HHMMSS>.json
  ```
  and update a symbolic/static link or pointer at:
  ```text
  reports/benchmarks/latest.json
  ```
* **Schema Contract**:
  ```json
  {
    "timestamp": "2026-10-06T10:00:00Z",
    "git_commit": "abcdef1",
    "configuration": {
      "concurrency": 20,
      "arrival_rate_rps": 250,
      "total_requests": 5000,
      "duration_seconds": 20.0
    },
    "metrics": {
      "ingestion": {
        "p50_ms": 4.2,
        "p90_ms": 8.1,
        "p99_ms": 14.5,
        "throughput_rps": 249.8
      },
      "worker_clearing_sla": {
        "p50_ms": 45.0,
        "p90_ms": 95.0,
        "p99_ms": 180.0,
        "max_clearing_ms": 230.0
      },
      "errors": {
        "failed_requests": 0,
        "timeout_errors": 0,
        "rate_limit_rejections": 0
      }
    }
  }
  ```

### B. Dual-Layer Profiling Architecture
* **Ingestion Gateway Latency**: Measure HTTP ingestion response time (`latency = response_received - request_sent`) while the broker queue is under deliberate background saturation. Asserts that API producers remain responsive regardless of worker backlog.
* **Worker End-to-End Clearing SLA**: Measure elapsed wall-clock duration from task submission until database terminal settlement (`clearing_sla = settled_at - created_at`). Asserts that workers meet SLA thresholds under sustained concurrent load.

### C. Arrival Rate Pacing via Little's Law
* **Rule**: Benchmark load harnesses must implement arrival-rate pacing (`--rate <req/s>`) rather than unconstrained simultaneous bursts (`asyncio.gather(*[all_requests])`).
* **Rationale**: Unconstrained bursts trigger artificial client-side OS TCP socket backlog serialization, causing skewed latency measurements that reflect client queue contention rather than server performance.
* **Pacing Implementation**:
  ```python
  import asyncio
  import time

  async def paced_benchmark(total_requests: int, target_rate_rps: float):
      interval = 1.0 / target_rate_rps
      start_time = time.perf_counter()
      tasks = []

      for i in range(total_requests):
          scheduled_time = start_time + (i * interval)
          delay = scheduled_time - time.perf_counter()
          if delay > 0:
              await asyncio.sleep(delay)
          tasks.append(asyncio.create_task(dispatch_request(i)))

      await asyncio.gather(*tasks)
  ```

### D. Historical Evolution Tracking
* **Standard**: Compare current benchmark metrics against `reports/benchmarks/latest.json`.
* **Regression Gate**: Catch performance regressions between commits (e.g., P99 latency degradation $> 15\%$) during release qualification or continuous profiling runs.
* **Audit Trail**: Maintain historical JSON reports to provide empirical audit tables for production capacity planning.
