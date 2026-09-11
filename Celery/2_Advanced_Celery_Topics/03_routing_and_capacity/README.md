# 03: Routing and Capacity

Build a job service with `critical`, `default`, and `bulk` queues.

## Deliverables

- Explicit task routing and queue declarations.
- Workers with documented pool, concurrency, prefetch, and rate-limit settings.
- Task batching using `chunks` to control prefetch buffer consumption and broker message volume for the `bulk` queue.
- Load tests showing queue latency and throughput under contention.
- Time limits and graceful handling of rejected or expired work.

## Evidence

Publish a capacity note with workload assumptions, measurements, and the reason for each worker setting.
