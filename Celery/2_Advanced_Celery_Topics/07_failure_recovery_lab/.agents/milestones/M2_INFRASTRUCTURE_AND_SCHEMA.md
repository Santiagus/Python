# Milestone 2: Infrastructure, Multi-Container Orchestration & Database Schema

> **Module**: `07_failure_recovery_lab`  
> **Milestone**: M2  
> **Status**: **Complete**  
> **Reference SSOT**: [init.sql](../../init.sql) | [shared/amqp_topology.py](../../shared/amqp_topology.py) | [docker-compose.yml](../../docker-compose.yml)

This document records the execution boundary, technical invariants, and completed micro-commits for Milestone 2.

---

## 1. Scope Boundary & Fences

* **In-Scope Files**:
  - `requirements_api.txt`, `requirements_dev.txt`, `services/*/requirements.txt`
  - `init.sql` (PostgreSQL 16 relational DDL, partial indexes, check constraints)
  - `shared/amqp_topology.py` (Kombu AMQP 0-9-1 declarations: exchanges, queues, dead-letter routing)
  - `docker/rabbitmq/definitions.json`, `docker/rabbitmq/rabbitmq.conf`
  - `Dockerfile.api`, `services/worker/Dockerfile`, `services/bank_simulator_api/Dockerfile`
  - `docker-compose.yml` (multi-container orchestrator)
  - `services/worker/celery_app.py` (Celery app with `acks_late=True`, `reject_on_worker_lost=True`)
  - Minimal health route skeletons (`app/main.py`, `services/bank_simulator_api/main.py`)
  - Unit tests: `tests/unit/test_amqp_topology.py`, `test_init_sql.py`, `test_docker_compose.py`, `test_worker_celery_app.py`, `test_app_health.py`, `test_bank_simulator_health.py`
  - `.vscode/launch.json` (just-in-time progressive debug configuration)

* **Out-of-Scope Files**:
  - Full domain models & schemas (reserved for **Milestone 3**)
  - Bank clearinghouse simulation logic (reserved for **Milestone 3**)
  - Celery consumer settlement tasks (reserved for **Milestone 3**)
  - Public wire ingestion API routes (reserved for **Milestone 4**)
  - Chaos injection harnesses (reserved for **Milestone 5**)

---

## 2. Technical Contracts & Invariants

* **Index Deduplication Invariant**: Zero explicit `CREATE INDEX` on unique columns (`id`, `idempotency_key`).
* **Partial Index for Active States**: `idx_wire_in_flight_status` strictly indexes active states (`WHERE status IN ('processing', 'submitted_to_bank')`).
* **Kombu AMQP Topology**:
  - Exchange `wire.direct` routes `wire.settlement.critical` to queue `wire.settlement.critical`.
  - Queue `wire.settlement.critical` configures DLX `x-dead-letter-exchange: wire.dlx` and routing key `x-dead-letter-routing-key: wire.settlement.dlq`.
* **Worker Execution Invariants**: Celery configured with `task_acks_late = True`, `task_reject_on_worker_lost = True`, `worker_prefetch_multiplier = 1`.

---

## 3. Micro-Commit Execution Record

| Step | Single-Line Conventional Commit | Staged Artifacts |
| :---: | :--- | :--- |
| **1** | `chore(deps): declare base dependencies in requirements manifests` | `requirements_api.txt`, `requirements_dev.txt`, `services/*/requirements.txt` |
| **2** | `feat(db): declare postgresql 16 relational ddl in init.sql with partial index` | `init.sql`, `tests/unit/test_init_sql.py` |
| **3** | `feat(amqp): declare kombu exchanges and queues topology in shared` | `shared/amqp_topology.py`, `tests/unit/test_amqp_topology.py` |
| **4** | `chore(rabbitmq): configure pre-loaded rabbitmq topology definitions` | `docker/rabbitmq/definitions.json`, `docker/rabbitmq/rabbitmq.conf` |
| **5** | `feat(worker): configure celery app with acks_late and lost worker rejection` | `services/worker/celery_app.py`, `tests/unit/test_worker_celery_app.py` |
| **6** | `chore(orchestration): declare multi-container compose topology` | `docker-compose.yml`, `tests/unit/test_docker_compose.py` |
| **7** | `feat(api): define minimal api and bank simulator health check skeletons` | `app/main.py`, `services/bank_simulator_api/main.py`, health tests |
| **8** | `chore(debug): configure progressive vs code compound debug environments` | `.vscode/launch.json` |

---

## 4. Verification & Acceptance Gates

* **Docker Cluster Health**: All containers start and pass health probes (`SELECT 1`, `rabbitmq-diagnostics ping`, `/health`).
* **Unit Test Coverage**: 100% statement coverage achieved across all M2 artifacts (`tests/unit/`).
* **Static Analysis**: `ruff check .` and `mypy .` passing with 0 errors.
