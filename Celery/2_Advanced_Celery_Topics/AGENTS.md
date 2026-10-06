# Project Instructions & Agent Guidelines

This workspace enforces strict backend engineering, distributed task execution, and testing standards across all modules.

---

## 1. Skill Specialization & Dynamic Routing

To prevent context bloat while preserving deep architectural guidance, detailed procedural runbooks, code examples, and configuration templates are modularized into dedicated skills under `.agents/skills/`. Agents should refer to the relevant skill when executing domain tasks:

| Concern / Workflow | Dedicated Skill | Core Scope |
| :--- | :--- | :--- |
| **Commit Strategy** | [celery-commit](.agents/skills/celery-commit/SKILL.md) | Single-line micro-commit slicing, mandatory review, zero-broken execution. |
| **Scaffolding & Architecture** | [celery-fastapi-scaffold](.agents/skills/celery-fastapi-scaffold/SKILL.md) | Clean Architecture, Shared Kernel (`shared/`), centralized Docker (`docker/`), FastAPI standards. |
| **Testing & Coverage** | [celery-test](.agents/skills/celery-test/SKILL.md) | 100% coverage, 4-tier test pyramid, hybrid testcontainers, in-flight state verification. |
| **Canvas & Task Workflows** | [celery-canvas-workflow](.agents/skills/celery-canvas-workflow/SKILL.md) | Canvas DAGs (`chain`/`chord`), `.s()` vs `.si()`, Result Envelope, hybrid queues, worker resilience. |
| **Performance & Resource Pooling** | [celery-perf-pooling](.agents/skills/celery-perf-pooling/SKILL.md) | Singleton initialization, persistent HTTP/DB pools, PgBouncer, L1/L2 caching, index tuning, durability. |
| **Benchmarking & Contention** | [celery-benchmarks](.agents/skills/celery-benchmarks/SKILL.md) | Structured JSON metrics, dual-layer profiling, Little's Law arrival-rate pacing, SLA tracking. |
| **Debug & REST Tooling** | [debug-setup](.agents/skills/debug-setup/SKILL.md) | Progressive launch configurations, compound multi-service debugging, `requests/requests.rest`. |
| **Documentation & Diagrams** | [celery-doc](.agents/skills/celery-doc/SKILL.md) | Modular docs, SSOT anti-bloat, Mermaid sequence diagrams, dual-layer milestones, docstrings. |
| **Diagnostics & Recovery** | [celery-fix](.agents/skills/celery-fix/SKILL.md) | Failure domain isolation, hanging chord recovery, pool starvation, serialization debugging. |
| **Observability (Opt-In)** | [celery-observability](.agents/skills/celery-observability/SKILL.md) | OpenTelemetry tracing, Prometheus `/metrics`, dual-probe health checks (strict opt-in only). |

---

## 2. Core Invariants & Engineering Standards

### System Persona
* **Persona**: Elite Senior Backend & Data Engineer (Python, FastAPI, Celery, RabbitMQ, PostgreSQL, Redis, Clean Architecture).
* **Guarantees**: Non-blocking asynchronous I/O, strict ACID guarantees, minor-unit financial precision (integer cents / `Decimal`), and robust fault-tolerant designs.

### Testing & Verification
* **100% Statement Coverage**: `pytest` with **100% statement coverage** required across all modules (`--cov-fail-under=100`).
* **4-Tier Test Separation**:
  - Unit (`tests/unit/`): In-memory, isolated, external calls mocked.
  - Integration (`tests/integration/`): Real database/broker transactions, API client routes.
  - Live E2E (`tests/e2e/test_live_e2e.py`): Full multi-process distributed stack.
  - Benchmarks (`tests/benchmarks/`): Contention and capacity tests.
* **Hybrid Testcontainers**: Auto-fallback to ephemeral containers (PostgreSQL, Redis, RabbitMQ) when local services are unavailable.
* **FinTech In-Flight State Visibility**: On `HTTP 202 ACCEPTED`, immediately persist an initial state machine record with `status="processing"` (or `"pending"`). Subsequent reads (`GET /resource/{id}`) must immediately return `HTTP 200 OK` reflecting active in-flight state, never `404 NOT FOUND`. Tests must assert `200 OK (processing)` before worker completion.
> **Full Testing Runbook**: See [celery-test](.agents/skills/celery-test/SKILL.md).

### Atomic Micro-Commit Strategy
* **Mandatory Review Prior to Commit & Push (Strict Non-Negotiable Invariant)**: Any change (code, documentation, test, or configuration) is strictly subject to user review prior to commit. Running `git commit` or `git push` without explicit confirmation and authorization from the user is **strictly forbidden under all circumstances**. Always present proposed changes, diffs, and verification results, and await explicit approval.
* **Single-Line Commit Messages**: Strictly formatted as a concise single-line Conventional Commit (`<type>(<scope>): <summary>`, $\le 72$ characters). Omit multi-line bodies or bullet points.
* **Granular Slicing Matrix**:
  - `chore(deps)`: Dependency manifests (`requirements_*.txt`).
  - `feat(db)`: Database DDL (`init.sql`) and configuration (with dedicated DDL test).
  - `feat(amqp)`: Kombu AMQP 0-9-1 topology (`shared/amqp_topology.py`) (with topology test).
  - `feat(models)`: Shared Kernel domain database models (`shared/models.py`) (with model test).
  - `feat(schemas)`: Shared Kernel Pydantic v2 domain schemas (`shared/schemas.py`) (with schema test).
  - `chore(rabbitmq)`: RabbitMQ pre-loaded definitions and config (`docker/rabbitmq/`).
  - `chore(docker)`: Centralized container Dockerfiles (`docker/Dockerfile.<service>`).
  - `feat(worker)`: Celery worker application configuration (`services/worker/celery_app.py`).
  - `feat(worker)`: Individual Celery task (**STRICTLY ONE TASK PER COMMIT**, with localized unit test).
  - `feat(api)`: Minimal API skeleton (`/health`, `/ready`), then routes and Swagger examples.
  - `chore(orchestration)`: Multi-container orchestration (`docker-compose.yml`).
  - `chore(debug)`: Just-in-time launch configurations (`.vscode/launch.json`).
* **Zero-Broken-Execution**: Every micro-commit must pass syntax, type checking (`mypy`), linting (`ruff`), and unit tests independently.
> **Full Commit Standards**: See [celery-commit](.agents/skills/celery-commit/SKILL.md).

### Clean Architecture & Shared Kernel (`shared/`)
* **Shared Kernel Boundary**: Domain persistence models (`shared/models.py`), domain contracts & validation schemas (`shared/schemas.py`), and Kombu AMQP topologies (`shared/amqp_topology.py`) strictly reside in `shared/`.
* **Unidirectional Flow**: `app -> shared`, `services/worker -> shared`, `scripts -> shared`. Headless workers must **never** import from `app` presentation layer.
* **Centralized Docker Packaging**: Centralize all Dockerfiles under top-level `docker/` (`docker/Dockerfile.api`, `docker/Dockerfile.worker`, etc.). Broker configs reside in `docker/<infra>/`. Build context is workspace root (`context: .`).
* **Service Naming & Isolation**: HTTP services use `_api` suffix (`services/bank_simulator_api/`), with dedicated minimal `requirements.txt`. Clear producer (`app/dispatcher.py`) vs consumer (`services/worker/tasks/`) separation. Tasks partitioned by business domain (`tasks/payouts.py`), never by priority/queue. Uniform `snake_case`.
> **Full Scaffolding Guidelines**: See [celery-fastapi-scaffold](.agents/skills/celery-fastapi-scaffold/SKILL.md).

### FastAPI Gateway Standards
* **Async & Logging**: `async def` endpoints as default; pretty development logger (`datefmt="%H:%M:%S"`, truncated 8-character `req_id[:8]`).
* **Modular Middlewares**: Partitioned package under `app/middlewares/` (`correlation.py`, `error_handling.py`, `profiling.py`).
* **Validation & Precision**: Pydantic v2 schemas with `Field` constraints, `ConfigDict`, realistic `examples=[...]` (preventing 422s in `/docs`), and strict `Decimal` / integer cents for currency (stored as `NUMERIC(14, 2)`).
* **Zero-Refresh Response Generation**: Pre-generate primary keys (`uuid.uuid4()`) and UTC timestamps in the application layer. Never call `await session.refresh()` in write endpoints.
* **Atomic Idempotency**: Enforce idempotency via database `UNIQUE` constraints and catch `IntegrityError` instead of issuing speculative `SELECT` queries before `INSERT`.
* **Security & Tokenization**: FastAPI Security Dependencies (`Security(APIKeyHeader)` / `HTTPBearer`). Zero raw financial PII across brokers (edge tokenization, encrypted vault, masked audit fields).

### Celery Worker & AMQP Messaging
* **Serialization**: Strict JSON serialization (no ORM models, file descriptors, or sockets across brokers).
* **Signatures & Chords**: Explicit `.s()` vs `.si()` discipline. Result Envelope pattern (`{"status": "ok" | "degraded" | "failed", ...}`) for chord header tasks to prevent hanging callbacks.
* **Worker Resilience**: Configure workers with `acks_late=True` and `task_reject_on_worker_lost=True`.
* **Tiered Hybrid Routing**: Group tasks initially by SLA tier (`critical`, `default`, `bulk`) with fine-grained semantic routing keys (`domain.entity.action`). Split into dedicated queues only when compute/isolation demands it.
* **Layer Separation**: Kombu for wire-level AMQP 0-9-1 declarations; Celery for workflow DAGs.
> **Full Canvas & Workflow Runbook**: See [celery-canvas-workflow](.agents/skills/celery-canvas-workflow/SKILL.md).

### Performance, Resource Pooling & Database Tuning
* **Eager Singletons**: Initialize clients, database engines, session factories, and thread pool singletons at module load time to eliminate first-call cold-start latency.
* **Connection Pooling**: Outgoing HTTP clients share process-level instances with connection pooling (`httpx.Limits(max_keepalive_connections=20, max_connections=50)`).
* **Role-Based DB Pools**: Budget worker child processes with lightweight pools (`pool_size=2, max_overflow=2`) and API gateways with larger capacity (`pool_size=10, max_overflow=20`), keeping total connections under PostgreSQL limits.
* **PgBouncer Multiplexing**: Deploy in transaction pooling mode (`POOL_MODE=transaction`) with `statement_cache_size: 0` in asyncpg.
* **Multi-Tier Caching**: L1 process memory cache with TTL for static reference data; L2 Redis for idempotency (`SET NX EX`) and rate limiting; DB is ACID source of truth.
* **Database Indexes & Durability**:
  - Index deduplication: never add `CREATE INDEX` on primary keys or `UNIQUE` columns.
  - Partial indexes for state machines: `WHERE status IN ('pending', 'processing')`.
  - Minimize SQL queries ($4 \to 1$ round-trips).
  - Default `synchronous_commit = on` for financial ledgers; modern NVMe settings (`shared_buffers = 512MB`, `wal_buffers = 16MB`, `random_page_cost = 1.1`).
* **Root-Cause Configuration Over Log Masking**: Eliminate warnings/errors via explicit driver/client configuration or Pydantic settings. Silencing loggers to mask protocol mismatches is strictly forbidden.
> **Full Pooling & Performance Guide**: See [celery-perf-pooling](.agents/skills/celery-perf-pooling/SKILL.md).

### Continuous Benchmarking & Telemetry Scope
* **Structured JSON Metrics**: Persist capacity/contention benchmarks to disk under `reports/benchmarks/benchmark_<YYYYMMDD_HHMMSS>.json` and update `latest.json`.
* **Dual-Layer Profiling**: Measure API Ingestion Latency (under queue saturation) and Worker End-to-End Clearing SLA (`cleared_at - created_at`).
* **Pacing**: Benchmark harnesses must implement Little's Law arrival-rate pacing (`--rate <req/s>`).
* **Strict Opt-In Telemetry**: OpenTelemetry tracing and Prometheus metrics (`/metrics`) are isolated in [celery-observability](.agents/skills/celery-observability/SKILL.md). Do **NOT** add telemetry dependencies unless explicitly requested.
> **Full Benchmarking Guide**: See [celery-benchmarks](.agents/skills/celery-benchmarks/SKILL.md).

### Debugging & Developer Experience (DX)
* **Progressive Launch Configurations**: In `.vscode/launch.json`, generate debug configurations strictly for services and entry points that currently exist and are runnable.
* **Compound Multi-Service Configurations**: Provide compound debug configurations (`compounds` with `"stopAll": true`) to launch and debug concurrent services together.
* **Interactive REST**: Maintain self-contained test scenarios in `requests/requests.rest` concurrently with endpoints and tests.
* **Pre-Commit Verification**: Run quality checks via `scripts/run_local_ci.sh` linked to git hooks and `.pre-commit-config.yaml`.
> **Full Debug Runbook**: See [debug-setup](.agents/skills/debug-setup/SKILL.md).

### Documentation Architecture & Anti-Bloat
* **Modular Documentation Partitioning**:
  - `README.md`: Executive summary, business impact, quickstart, compliance matrix.
  - `docs/ARCHITECTURE_AND_STANDARDS.md`: System topology, clean architecture rules, performance/security standards.
  - `docs/USE_CASES.md`: Business workflows, actor interactions, recovery scenarios.
  - `docs/TEST_PLAN.md`: Test strategy, test matrix table, hybrid testcontainers setup.
  - `docs/MILESTONES.md`: Milestone roadmap (M1–M6), phase summaries, acceptance criteria tracking.
  - `docs/SEQUENCE_DIAGRAMS.md`: Sequence diagrams covering all distributed execution and failure paths.
  - `.agents/milestones/M<N>_<SLUG>.md`: Granular agent procedural execution runbooks with scope fences, micro-commit sequences, and verification gates.
* **Anti-Bloat & Single Source of Truth (SSOT)**: Never copy-paste raw implementation code (`init.sql`, Pydantic models, Kombu definitions) into markdown docs. Link to source files and illustrate visually using Mermaid (`erDiagram`, `classDiagram`, `flowchart`).
* **Dual-Layer Milestone Generation**: Always maintain human roadmap (`docs/MILESTONES.md`) and agent execution runbooks (`.agents/milestones/M<N>_<SLUG>.md`) concurrently. Milestone 1 focuses strictly on planning and architecture (no application code, Dockerfiles, or DB DDL).
* **Mermaid Render Verification**: Quote labels containing special characters (`id["Label (Extra)"]`) and ensure block closure (`end`).
* **Code Readability**: Google-style docstrings on all functions; numbered block comments (`# 1. ...`, `# 2. ...`) for multi-stage execution flows.
> **Full Documentation Standards**: See [celery-doc](.agents/skills/celery-doc/SKILL.md).

### File Integrity & Local Invariants
* **Creation Mask (`umask 022`)**: Execute commands creating files or directories with `umask 022` (directories `755`, regular files `644`). Never generate `777` or `666` permissions.
* **Zero Backstage File Modification**: Author fully formatted, sorted, and lint-clean code upfront on the first attempt. Avoid unrequested automated rewrites or editor buffer conflicts (`files.autoSave: "off"`, `editor.formatOnSave: false`).
