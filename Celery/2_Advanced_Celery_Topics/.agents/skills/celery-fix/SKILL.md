---
name: celery-fix
description: >-
  Analyze errors, tracebacks, task deadlocks, hanging chords, broker bottlenecks,
  or database issues and propose clean architecture refactors. Use this skill when
  asked to debug an error, fix a failure, troubleshoot Celery workers/brokers, or
  optimize performance.
---

# Celery & Distributed Systems Troubleshooting & Refactoring

This skill guides root-cause analysis and clean architecture refactoring for backend microservices, Celery workers, RabbitMQ brokers, Redis backends, and PostgreSQL databases.

---

## 1. Systematic Diagnostic Workflow

When an error, traceback, hanging task, or test failure is encountered:

### Step 1: Isolate the Failure Domain
Identify which layer is failing:
- **Broker / Transport**: Connection timeouts, RabbitMQ channel closures, queue declaration mismatches, unacknowledged message buildup.
- **Worker Execution**: Celery worker crashes, OOM errors, task timeouts (`soft_time_limit`, `time_limit`), unhandled exceptions.
- **Canvas Coordination**: Hanging chords (where callback is never invoked), argument signature mismatches (`TypeError: takes X positional arguments but Y were given`), empty groups.
- **Serialization Boundary**: `EncodeError`, `DecodeError`, unpickleable objects, or attempting to pass ORM models/sockets across the broker.
- **Database / ACID**: Deadlocks, lock timeouts, constraint violations (`IntegrityError`, `CheckViolation`), uncommitted sessions, async connection leaks.
- **Concurrency & Race Conditions**: Stale reads, non-atomic increments, competing consumer races.

### Step 2: Extract & Inspect Evidence
- Check worker logs with `--loglevel=DEBUG`.
- Inspect RabbitMQ queue depths (`celery inspect active`, `celery inspect reserved`).
- Inspect Redis keys and TTLs for task results (`keys celery-task-meta-*`).
- Check PostgreSQL active locks:
  ```sql
  SELECT pid, query, state, age(clock_timestamp(), query_start) FROM pg_stat_activity WHERE state != 'idle';
  ```

---

## 2. Common Failure Modes & Verified Fixes

### A. Hanging Chords (Callback Never Fires)
* **Root Cause**: One or more tasks in the chord header raised an unhandled exception before returning a result, leaving the Redis counter un-decremented.
* **Refactor**: Apply the **Result Envelope Pattern**. Wrap header task returns in an envelope dictionary (`{"status": "ok" | "degraded", "result": ..., "errors": [...]}`) and catch task exceptions so every header task cleanly delivers a result to the barrier.

### B. Canvas Signature `TypeError` Mismatch
* **Root Cause**: Using `.s()` when the task shouldn't receive the parent result, or using `.si()` when upstream output was expected.
* **Rule**:
  - `task_b.s()`: `task_b` will receive `result_a` as its first argument: `task_b(result_a, *args, **kwargs)`.
  - `task_b.si()`: `task_b` ignores upstream result entirely: `task_b(*args, **kwargs)`.

### C. Broker Serialization Failure (`Kombu` / JSON Errors)
* **Root Cause**: Task arguments contain an async engine, SQLAlchemy ORM instance, file handle, or datetime object not serialized to ISO 8601.
* **Refactor**: Strip objects down to primitive identifiers (UUID strings, integer IDs, filesystem paths) and let the worker fetch fresh database state within its own session.

### D. PostgreSQL Connection Pool Starvation
* **Root Cause**: SQLAlchemy `asyncpg` sessions left unclosed in exception paths or inside Celery tasks that don't dispose of connections.
* **Refactor**: Always use `async with async_sessionmaker() as session:` context managers and configure `pool_pre_ping=True` with explicit `pool_size` and `max_overflow`.

---

## 3. Refactoring Principles
When applying a fix:
1. **Preserve Clean Architecture**: Maintain separation between domain logic (pure calculations), persistence (repositories/models), and distributed coordination (Celery tasks).
2. **Idempotency**: Ensure tasks can safely run more than once without generating duplicate side-effects (e.g., unique constraints, conditional inserts, upserts).
3. **Verify with Tests**: Add a regression test reproducing the exact failure scenario before confirming the fix, maintaining **100% test coverage**.

