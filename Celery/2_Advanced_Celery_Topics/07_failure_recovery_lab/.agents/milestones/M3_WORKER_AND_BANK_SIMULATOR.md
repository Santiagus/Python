# Milestone 3: Domain Models, Bank Simulator API & Celery Worker Consumer

> **Module**: `07_failure_recovery_lab`  
> **Milestone**: M3  
> **Status**: Complete  
> **Reference SSOT**: [docs/ARCHITECTURE_AND_STANDARDS.md](../../docs/ARCHITECTURE_AND_STANDARDS.md) | [docs/SEQUENCE_DIAGRAMS.md](../../docs/SEQUENCE_DIAGRAMS.md) | [init.sql](../../init.sql)

This specification defines the granular, agent-executable runbook for Milestone 3. AI agents must execute this document sequentially, adhering to scope boundaries, micro-commit slicing, and verification gates.

---

## 1. Scope Boundary & Fences

* **In-Scope Files (Allowed to create / modify)**:
  - `shared/models.py` (SQLAlchemy / dataclass domain models mapping `init.sql`)
  - `shared/schemas.py` (Pydantic v2 schemas for wires, bank simulator, ledger entries)
  - `services/bank_simulator_api/main.py` (and helper modules if needed, implementing idempotent Fedwire clearing)
  - `services/worker/tasks/` (`__init__.py`, `settlement.py`, `audit.py`)
  - `tests/unit/test_models.py`
  - `tests/unit/test_schemas.py`
  - `tests/unit/test_bank_simulator_routes.py`
  - `tests/unit/test_task_settlement.py`
  - `tests/unit/test_task_audit.py`

* **Out-of-Scope Files (Strictly forbidden to modify in M3)**:
  - `app/` (FastAPI public ingestion routes and gateway dispatcher — reserved for **Milestone 4**)
  - `requests/requests.rest` (REST client test suite — reserved for **Milestone 4**)
  - `scripts/chaos_harness.py` (Chaos injection harness — reserved for **Milestone 5**)
  - `tests/integration/` (Chaos failure injection suites — reserved for **Milestone 5**)
  - `tests/e2e/`, `tests/benchmarks/` (Live multi-process verification — reserved for **Milestone 6**)

---

## 2. Technical Contracts & Invariants

1. **Two-Phase Provider Inquiry (Anti-Double-Disbursement Invariant)**:
   - On worker execution (or redelivery after `SIGKILL`), worker must **never** blindly call the bank disbursement endpoint.
   - **Phase 1**: Execute inquiry `GET /v1/wires/{idempotency_key}` against Bank Simulator.
     - If response is `200 OK` (`status: "CONFIRMED"`): Bank already processed the wire. Skip payout call, advance DB state directly to `settled`.
     - If response is `404 NOT FOUND`: Wire was never received by bank. Proceed to Phase 2.
   - **Phase 2**: Execute `POST /v1/wires/settle` with matching `idempotency_key`.

2. **Celery Worker Execution Discipline**:
   - Tasks must strictly inherit `acks_late=True` and `reject_on_worker_lost=True`.
   - Message ACK to RabbitMQ occurs **strictly after** PostgreSQL commits the transaction.
   - If worker dies mid-execution, broker requeues message to another worker pod.

3. **ACID Transaction & Row-Level Locking**:
   - Query wire with row-level lock: `SELECT * FROM wire_transfers WHERE id = :id FOR UPDATE;`
   - Guard against duplicate execution: if `status` is already `settled` or `failed`, abort cleanly.
   - Double-entry ledger insertion into `ledger_journal` with matching debit and credit lines in integer cents (`amount_cents`). Zero ledger drift ($0\text{ cents}$).

4. **Financial Durability & Precision**:
   - Zero float math: All calculations done in minor units (`int` cents).
   - In Pydantic: `Decimal` validated and converted to integer cents.

---

## 3. Ordered Micro-Commit Execution Sequence

Strictly execute one atomic slice per commit. Every commit must pass syntax, type check, and localized unit tests before moving to the next.

| Step | Single-Line Conventional Commit ($\le 72$ chars) | Target Files | Dedicated Test File |
| :---: | :--- | :--- | :--- |
| **1** | `feat(models): define wire transfer and ledger domain models` | `shared/models.py` | `tests/unit/test_models.py` |
| **2** | `feat(schemas): define pydantic v2 schemas with monetary validation` | `shared/schemas.py` | `tests/unit/test_schemas.py` |
| **3** | `feat(simulator): implement idempotent bank clearing endpoints` | `services/bank_simulator_api/main.py` | `tests/unit/test_bank_simulator_routes.py` |
| **4** | `feat(worker): implement two-phase inquiry settlement celery task` | `services/worker/tasks/settlement.py` | `tests/unit/test_task_settlement.py` |
| **5** | `feat(worker): implement wire audit log and dlq quarantine task` | `services/worker/tasks/audit.py` | `tests/unit/test_task_audit.py` |

---

## 4. Verification & Acceptance Gates

Before requesting user review or marking M3 complete, execute the following commands in order:

```bash
# 1. Run localized unit tests with statement coverage
.venv/bin/pytest tests/unit/test_models.py tests/unit/test_schemas.py tests/unit/test_bank_simulator_routes.py tests/unit/test_task_settlement.py tests/unit/test_task_audit.py -v --cov=services --cov=shared --cov-report=term-missing

# 2. Verify 100% statement coverage across M3 targets
.venv/bin/pytest tests/unit/ -v --cov=services/bank_simulator_api --cov=services/worker/tasks --cov=shared --cov-fail-under=100

# 3. Static type analysis
.venv/bin/mypy shared services/bank_simulator_api services/worker/tasks

# 4. Code style and linting
.venv/bin/ruff check shared services/bank_simulator_api services/worker/tasks
```
