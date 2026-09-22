# Project Instructions & Agent Guidelines

This project enforces strict backend engineering, distributed task execution, and testing standards. For detailed rules and guidelines, see [GEMINI.md](/GEMINI.md).

## Quick Summary of Invariants
* **Persona**: Elite Senior Backend & Data Engineer (Python, FastAPI, Celery, RabbitMQ, PostgreSQL, Redis, Clean Architecture).
* **Testing**: `pytest`, **100% test coverage** required, hybrid testcontainers pattern for PostgreSQL/Redis/RabbitMQ (auto-fallback if no local services).
* **Testing Standards**: `pytest`, **100% test coverage** required, hybrid testcontainers pattern for PostgreSQL/Redis/RabbitMQ. Strict 4-tier test directory separation: unit (`tests/unit/`), integration (`tests/integration/`), live multi-process E2E (`tests/e2e/test_live_e2e.py`), and capacity benchmarks (`tests/benchmarks/`).
* **Debugging**: Multi-service and compound debug configs in `.vscode/launch.json`; self-contained test scenarios in `requests/requests.rest` (generated concurrently with endpoints and tests).
* **FastAPI Standards**:
  - `async def` endpoints as default.
  - Development logger with pretty formatter (`datefmt="%H:%M:%S"`, truncated 8-character UUID `req_id[:8]`, no headers for standard HTTP fields).
  - Modular `app/middlewares/` package partitioned by concern (`correlation.py`, `error_handling.py`, `profiling.py`) with unified registration.
  - Pydantic v2 schemas with `Field` validation constraints and `ConfigDict`.
  - Strict `Decimal` for all monetary and calculated financial fields (stored as `NUMERIC(14, 2)` and processed internally in minor-unit integer cents).
  - Realistic specimen defaults and examples (`examples=[...]`) across all schemas so Swagger UI (`/docs`) "Try it out" executes cleanly without $422$ errors.
* **Documentation & Readability**:
  - `docs/TEST_PLAN.md`, `docs/ARCHITECTURE_AND_STANDARDS.md`, and Mermaid `flowchart` and `sequenceDiagram` diagrams covering all execution paths.
  - Mandatory Google-style docstrings for **every** method and function.
  - Step-by-step numbered block comments (`# 1. ...`, `# 2. ...`) for multi-stage or long functions so execution flow is effortlessly readable from method calls and headers.
* **Celery Architecture & Abstraction Layers**:
  - Strict JSON serialization across brokers (no ORM models/sockets), canvas `.s()` vs `.si()` signature discipline, and Result Envelope pattern for resilient chord execution.
  - Explicit distinction between Application Layer (Celery workflows) and Driver/Protocol Layer (Kombu for AMQP 0-9-1 framing, exchanges, queues, DLX, and TTL arguments).
  - **Tiered Hybrid Queue Topology**: Group tasks initially by SLA tier (`critical`, `default`, `bulk`) to conserve compute, prevent broker connection bloat, and avoid managing dozens of idle worker pods. Always enforce fine-grained, semantic routing keys (`domain.entity.action` / `payment.standard.receipt` vs `payment.standard.webhook`) from day one. Split into dedicated queues only when a task's volume, latency variance, third-party unreliability, or heavy memory/CPU footprint demands physical isolation (requiring zero producer code changes). All design decisions must be explicitly reflected in project documentation.
* **Production Reference Patterns & Clean Boundaries**:
  - Clear Producer (`app/dispatcher.py`) vs. Consumer (`services/worker/tasks/`) separation. Never create conflicting `app/tasks.py` files.
  - Domain-partitioned tasks: group tasks strictly by business domain (`tasks/payouts.py`, `tasks/settlements.py`, `tasks/notifications.py`), NEVER by queue or priority level (`tasks/critical.py`).
  - Flat service hierarchies: never nest external mock services or partner simulators inside worker directories (e.g., NEVER `services/worker/simulators/`).
  - Service naming convention: any standalone component or mock exposing an HTTP endpoint must include `_api` as a suffix or prefix (e.g., `services/bank_simulator_api/`, `services/provider_api/`).
  - Dedicated service isolation: autonomous services own colocated `Dockerfile` and minimal `requirements.txt` (`services/worker/`, `services/bank_simulator_api/`). Never bloat headless workers with web servers (`uvicorn`/`fastapi`) or mock APIs with Celery/PostgreSQL.
  - Uniform Pythonic `snake_case` naming: enforce `snake_case` across all dependency manifests, configuration files, and script names (`requirements_api.txt`, `requirements_dev.txt`). Never mix kebab-case with snake_case across the repository.
* **Enterprise Security & Tokenization Invariants**:
  - Access security via FastAPI Security Dependencies (`Security(APIKeyHeader)` / `HTTPBearer`) over raw middleware for native OpenAPI `/docs` "Authorize" 🔒 integration, clean route exemptions, and RBAC scopes. Prefixed, hashed keys at rest (`sk_live_...`).
  - Zero-Knowledge Broker: strictly zero raw financial PII (card PANs, bank accounts, routing numbers) across Celery task arguments or RabbitMQ queues. Edge tokenization, encrypted vault storage, and masked audit fields (`account_mask: "******7890"`).
* **High-Performance Resource Management & Pooling Invariants**:
  - **Eager Singleton Initialization at Module Load**: Initialize all shared client, connection, and thread pool singletons (`_shared_client`, `_engine`, `_session_factory`, `_sync_executor`) at module load time to eliminate first-call cold-start/warm-up latency. Never defer initialization lazily to the first transaction.
  - **Shared Client Connection Factories**: Outgoing network clients (`BankSimulatorClient`) must share a process-level client instance with explicit connection pooling (`httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)`). Tasks reuse persistent TCP keep-alive sockets rather than opening and tearing down ephemeral sockets per request, preventing socket pileup in `TIME_WAIT`.
  - **Role-Based Database Connection Pool Budgeting**: In prefork multi-process architectures, single-threaded worker child processes execute strictly one task at a time and must be budgeted with lightweight pools (`pool_size=2, max_overflow=2`), while the API gateway allocates higher capacity (`pool_size=10, max_overflow=20`). This prevents exhausting PostgreSQL's `max_connections` ($N \times 30$ vs budgeted total $< 30$).
  - **Shared Process Thread Pool for Sync-in-Async Bridging**: In `run_sync()`, reuse an eagerly-initialized module-level `ThreadPoolExecutor(max_workers=4)` rather than constructing and tearing down ephemeral executors on every call.
  - **Kombu AMQP Broker Pooling**: Always configure `broker_pool_limit=10` and `broker_connection_retry_on_startup=True` in Celery.
  - **Eager Boot Warm-Up (`@signals.worker_process_init` & FastAPI `lifespan`)**: When Celery child processes fork, immediately re-initialize and warm the event loop, worker-budgeted DB pool, and HTTP client at boot time so the first task executes with sub-25ms P99 latency. In FastAPI `lifespan`, pre-warm database pools on startup with a `SELECT 1` ping.




* **Continuous Benchmark Profiling & Performance History Invariants**:
  - **Structured JSON Benchmark Persistence**: All capacity and contention benchmarks (`scripts/load_test_*.py`) must persist structured execution metrics to disk under `reports/benchmarks/benchmark_<YYYYMMDD_HHMMSS>.json` and update `reports/benchmarks/latest.json`.
  - **Dual-Layer Profiling**: Separate and measure both API Ingestion Latency (under background queue saturation) and Worker End-to-End Clearing SLA (`cleared_at - created_at`).
  - **Arrival Rate Pacing**: Benchmark load harnesses must implement Little's Law arrival-rate pacing (`--rate <req/s>`) rather than unconstrained simultaneous bursts to prevent client-side OS TCP socket backlog serialization from skewing distributed SLA measurements.
  - **Historical Evolution Tracking**: Use saved JSON reports to track latency trends over time, catch performance regressions between commits, and generate empirical capacity tables for production audits.
