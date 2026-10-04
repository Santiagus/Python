# Milestone 5: Automated Chaos Harness & Failure Injection Test Suites

> **Module**: `07_failure_recovery_lab`  
> **Milestone**: M5  
> **Status**: Pending (Follows M4)  
> **Status**: Complete  
> **Reference SSOT**: [docs/ARCHITECTURE_AND_STANDARDS.md](../../docs/ARCHITECTURE_AND_STANDARDS.md) | [docs/SEQUENCE_DIAGRAMS.md](../../docs/SEQUENCE_DIAGRAMS.md)

This specification defines the agent execution runbook for Milestone 5.

---

## 1. Scope Boundary & Fences

* **In-Scope Files (Allowed to create / modify)**:
  - `scripts/chaos_harness.py` (CLI chaos harness orchestrating Docker/process failures)
  - `tests/integration/`
    - `conftest.py` (hybrid testcontainers setup for Postgres, RabbitMQ)
    - `test_worker_crash_recovery.py` (Worker SIGKILL mid-flight test)
    - `test_acknowledgement_modes.py` (Early-ack vs Late-ack comparison)
    - `test_broker_restart_recovery.py` (RabbitMQ crash & restart durable recovery)
    - `test_dead_letter_quarantine.py` (Poison pill DLX/DLQ routing)
  - `tests/unit/test_chaos_harness.py`

* **Out-of-Scope Files (Strictly forbidden to modify in M5)**:
  - `tests/e2e/test_live_e2e.py` (Live cluster multi-process E2E — reserved for **Milestone 6**)
  - `tests/benchmarks/` (MTTR benchmarks — reserved for **Milestone 6**)
  - `reports/experiments/` (Evidence artifact persistence — reserved for **Milestone 6**)

---

## 2. Technical Contracts & Invariants

1. **Failure Experiment 1 (Worker SIGKILL)**:
   - Worker killed via `os.kill(pid, signal.SIGKILL)` during settlement execution.
   - Assert RabbitMQ redelivers task (`redelivered=True`).
   - Assert surviving worker acquires lock, runs two-phase inquiry, and completes without double-payout.
2. **Failure Experiment 2 (Early-Ack vs Late-Ack)**:
   - Verify that with `acks_late=False`, SIGKILL results in silent message loss.
   - Verify that with `acks_late=True`, zero messages are lost.
3. **Failure Experiment 3 (Broker Outage)**:
   - Broker container stopped and restarted.
   - Assert durable queues and disk-backed messages recover cleanly upon boot.
4. **Failure Experiment 4 (Poison Pill Quarantine)**:
   - Malformed payload routed to DLQ (`wire.settlement.dlq`).
   - Validate `x-death` headers preserve exception reason and original routing key.

---

## 3. Ordered Micro-Commit Execution Sequence

| Step | Single-Line Conventional Commit ($\le 72$ chars) | Target Files | Dedicated Test File |
| :---: | :--- | :--- | :--- |
| **1** | `feat(chaos): implement programmatic chaos injection harness` | `scripts/chaos_harness.py` | `tests/unit/test_chaos_harness.py` |
| **2** | `test(recovery): verify worker sigkill redelivery and idempotency` | `tests/integration/` | `tests/integration/test_worker_crash_recovery.py` |
| **3** | `test(recovery): verify early vs late acknowledgement trade-offs` | `tests/integration/` | `tests/integration/test_acknowledgement_modes.py` |
| **4** | `test(recovery): verify rabbitmq broker restart and durable recovery` | `tests/integration/` | `tests/integration/test_broker_restart_recovery.py` |
| **5** | `test(recovery): verify poison pill dead-letter exchange quarantine` | `tests/integration/` | `tests/integration/test_dead_letter_quarantine.py` |

---

## 4. Verification & Acceptance Gates

```bash
# 1. Run integration tests under hybrid testcontainers
.venv/bin/pytest tests/integration/ -v

# 2. Static type safety and linting
.venv/bin/mypy scripts/chaos_harness.py
.venv/bin/ruff check scripts/chaos_harness.py tests/integration/
```
