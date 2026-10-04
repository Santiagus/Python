# Milestone 6: Distributed Live E2E Verification, MTTR Benchmarks & Evidence Log

> **Module**: `07_failure_recovery_lab`  
> **Milestone**: M6  
> **Status**: Complete (100% Verified)  
> **Reference SSOT**: [docs/ARCHITECTURE_AND_STANDARDS.md](../../docs/ARCHITECTURE_AND_STANDARDS.md) | [docs/MILESTONES.md](../../docs/MILESTONES.md)

This specification defines the agent execution runbook for Milestone 6.

---

## 1. Scope Boundary & Fences

* **In-Scope Files (Allowed to create / modify)**:
  - `tests/e2e/test_live_e2e.py` (live end-to-end verification against Docker Compose cluster)
  - `tests/benchmarks/test_recovery_benchmarks.py` (MTTR and capacity benchmarks)
  - `reports/benchmarks/latest.json` (structured execution benchmark metrics)
  - `reports/experiments/latest_experiment_log.json`
  - `docs/EXPERIMENT_LOG.md` (empirical disaster recovery audit evidence)
  - `docs/MILESTONES.md` (update deliverables compliance matrix to 100% complete)

* **Out-of-Scope Files**:
  - Do NOT modify established core application architecture (`services/`, `app/`, `shared/`) unless repairing an empirical benchmark regression.

---

## 2. Technical Contracts & Invariants

1. **Live Distributed Verification Invariant**:
   - Tests execute against real multi-container Docker cluster (`docker compose up -d`).
   - Asserts zero double-disbursements across all concurrently executed wires.
   - Asserts mathematical ledger balance ($0\text{ cents drift}$, `SUM(debit) == SUM(credit)`).
2. **MTTR Benchmark Invariant**:
   - Programmatically measures Mean Time to Recovery (MTTR) under load.
   - Paces requests using Little's Law arrival rate.
   - Persists structured metrics to `reports/benchmarks/`.
3. **Structured Audit Evidence**:
   - Generates verifiable markdown evidence log in `docs/EXPERIMENT_LOG.md`.

---

## 3. Ordered Micro-Commit Execution Sequence

| Step | Single-Line Conventional Commit ($\le 72$ chars) | Target Files | Dedicated Test File |
| :---: | :--- | :--- | :--- |
| **1** | `test(e2e): implement live multi-process end-to-end verification suite` | `tests/e2e/test_live_e2e.py` | `tests/e2e/test_live_e2e.py` |
| **2** | `test(benchmarks): implement mttr and recovery latency benchmark harness` | `tests/benchmarks/` | `tests/benchmarks/test_recovery_benchmarks.py` |
| **3** | `docs(evidence): persist empirical disaster recovery log and mttr metrics` | `reports/`, `docs/EXPERIMENT_LOG.md` | Verification log |
| **4** | `docs(milestones): mark all delivery milestones and compliance 100% complete` | `docs/MILESTONES.md` | Compliance audit |

---

## 4. Verification & Acceptance Gates

```bash
# 1. Run live E2E against running cluster
.venv/bin/pytest tests/e2e/test_live_e2e.py -v

# 2. Run benchmark suite
.venv/bin/pytest tests/benchmarks/test_recovery_benchmarks.py -v

# 3. Verify ledger balance in PostgreSQL
docker compose exec -T postgres psql -U postgres -d failure_recovery_lab -c "SELECT SUM(amount_cents) FROM ledger_journal WHERE entry_type = 'DEBIT';"
docker compose exec -T postgres psql -U postgres -d failure_recovery_lab -c "SELECT SUM(amount_cents) FROM ledger_journal WHERE entry_type = 'CREDIT';"
```
