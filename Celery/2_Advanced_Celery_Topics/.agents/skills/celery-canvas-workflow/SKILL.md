---
name: celery-canvas-workflow
description: >-
  Design and implement distributed Celery canvas workflows (chains, groups, chords),
  signature discipline (.s() vs .si()), Result Envelope patterns, error handling callbacks,
  and tiered AMQP routing topologies. Use this skill when orchestrating multi-task pipelines,
  chord barriers, errbacks, or queue routing architectures.
---

# Celery Canvas Workflows, Coordination & Routing Topologies

This skill guides the design and implementation of production-grade Celery workflows using canvas primitives (`chain`, `group`, `chord`), explicit signature semantics, resilient error handling, and tiered AMQP queue topologies.

---

## 1. Celery Architecture & Abstraction Layers

### A. Driver/Protocol vs. Application Layer Separation
* **Protocol / Driver Layer (Kombu)**: Defines AMQP 0-9-1 wire-level declarations: direct/topic exchanges, durable queues, dead-letter exchanges (`x-dead-letter-exchange`), message TTLs (`x-message-ttl`), and delivery modes. Declared in `shared/amqp_topology.py`.
* **Application Orchestration Layer (Celery)**: Defines business tasks, workflow DAGs, retry schedules, and canvas assemblies. Headless workers and API dispatchers import topology from `shared/amqp_topology.py` rather than declaring ad-hoc inline strings.

### B. Broker Serialization Boundary (Zero-Knowledge / Primitive Payloads)
* **Rule**: Strictly pass primitive, JSON-serializable identifiers (UUID strings, integer IDs, ISO 8601 timestamps) across brokers.
* **Banned**: Never pass SQLAlchemy ORM model instances, open file descriptors, network sockets, or binary blobs across Celery task signatures or RabbitMQ messages.
* **Worker Fetch Pattern**: Workers receive an entity ID, open their own isolated database session, and fetch fresh state under strict transaction isolation.

### C. Canvas Signature Discipline: `.s()` vs. `.si()`
* **`task.s(*args, **kwargs)` (Partial Signature)**:
  - Automatically prepends the parent task's return value as the first positional argument to `task`.
  - Use in sequential pipelines (`chain`) where step $N+1$ depends on the output of step $N$.
* **`task.si(*args, **kwargs)` (Immutable Signature)**:
  - Strictly ignores upstream output and executes with only the explicitly bound arguments.
  - Essential in chords and groups where parallel header tasks already have their inputs bound and should not receive unexpected positional arguments.

### D. Result Envelope Pattern (Resilient Chord Execution)
* **Problem**: In standard Celery chords, if any task in the chord header raises an unhandled exception, Celery aborts the task, the chord barrier counter in Redis is never decremented, and the chord callback **hangs indefinitely**.
* **Solution**: Header tasks must catch task-level exceptions and wrap output in a standardized Result Envelope:
  ```python
  from typing import Any

  def result_envelope(
      status: str,
      data: Any = None,
      error: str | None = None,
  ) -> dict[str, Any]:
      """Wrap task execution outcome in a resilient result envelope."""
      return {
          "status": status,  # "ok" | "degraded" | "failed"
          "data": data,
          "error": error,
      }
  ```
* **Chord Header Task Pattern**:
  ```python
  @celery_app.task(bind=True, acks_late=True)
  def header_step(self, item_id: str) -> dict[str, Any]:
      try:
          result = process_item(item_id)
          return result_envelope(status="ok", data=result)
      except RecoverableError as exc:
          logger.warning(f"Header step degraded for {item_id}: {exc}")
          return result_envelope(status="degraded", error=str(exc))
      except Exception as exc:
          logger.error(f"Header step failed for {item_id}: {exc}")
          return result_envelope(status="failed", error=str(exc))
  ```
* **Chord Callback Synthesis**: The callback receives an array of Result Envelopes, cleanly aggregates all successes, and handles degraded items without hanging.

### E. Worker Resilience & Late Acknowledgement
* **Standard Settings**:
  ```python
  celery_app.conf.update(
      task_acks_late=True,
      task_reject_on_worker_lost=True,
      worker_prefetch_multiplier=1,
      task_track_started=True,
  )
  ```
* **`task_acks_late=True`**: Message is acknowledged only *after* the task returns or completes. If a worker process is killed (`SIGKILL`, OOM) during execution, RabbitMQ redelivers the message to an available worker.
* **`task_reject_on_worker_lost=True`**: When a worker child process crashes unexpectedly, the master worker process rejects the message (`basic.nack(requeue=True)`) so it is re-queued immediately.

---

## 2. Tiered Hybrid Queue Topology

* **Tiered Slicing Principle**: Group tasks initially by SLA tier (`critical`, `default`, `bulk`) rather than provisioning a dedicated queue for every individual task. This conserves compute, prevents broker connection bloat, and avoids managing dozens of idle worker pods.
* **Fine-Grained Semantic Routing Keys**: Always enforce semantic routing keys (`domain.entity.action` — e.g., `payment.wire.execute`, `payment.standard.receipt`, `notification.email.send`) from day one:
  ```text
  Routing Key: <domain>.<sla_tier>.<action>
  Examples:
    - wire.critical.settle
    - wire.default.notify
    - wire.bulk.archive
  ```
* **Physical Isolation Triggers**: Split a task into a physically dedicated queue only when:
  1. The task volume creates sustained queue contention for other SLA tasks.
  2. The task has extreme latency variance (e.g. 50ms vs 45s).
  3. The task interfaces with an unreliable third-party partner API with frequent outages.
  4. The task requires a heavy CPU or memory footprint (isolated worker deployment).
* **Zero Producer Code Changes**: Because publishers emit semantic routing keys to topic exchanges, routing adjustments require only queue binding changes in `shared/amqp_topology.py`, requiring zero code modifications in API dispatchers.
