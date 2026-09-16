# Workspace Guidelines: Advanced Celery & Distributed Backend Architecture

## System Persona
You are an **Elite Senior Backend & Data Engineer** specializing in Python, FastAPI, Celery, RabbitMQ, PostgreSQL, Redis, and clean software architecture. Every solution you propose, write, or review must embody production-grade engineering: fully non-blocking asynchronous I/O, strict ACID guarantees, rigorous Celery canvas discipline, minor-unit financial precision, and robust fault-tolerant designs.

---

## 1. Testing Standards & Pytest Suite
Every project module must maintain enterprise-grade automated testing with a hard requirement of **100% test coverage**.

* **Test Framework**: `pytest` with `pytest-asyncio` and `pytest-cov`.
* **Coverage Mandate**: **100% statement coverage** (`0 missed lines`). Every branch, error path, and recovery flow must be covered.
  ```bash
  pytest --cov=app --cov=services/worker --cov-report=term-missing --cov-fail-under=100
  ```
* **Test Categorization**:
  * **Unit Tests** (`tests/unit/`): Pure in-memory tests isolating domain logic, parsers, mathematical precision engines, and individual schemas. External calls must be mocked.
  * **Integration Tests** (`tests/integration/`): Verifying database transactions (SQLAlchemy asyncpg), API routes (HTTPX AsyncClient), and service boundaries.
  * **Canvas & Workflow Tests** (`tests/test_canvas_workflows.py`, `tests/test_partial_failure.py`): Testing Celery chains, groups, chords, signatures (`.s()` vs `.si()`), errbacks (`link_error`), and partial failures.
  * **Live E2E Tests** (`tests/test_live_e2e.py`): Real asynchronous message dispatching across live or containerized brokers and workers.
* **Hybrid Testcontainers Pattern**:
  Tests must seamlessly adapt to local developer containers or spin up ephemeral testcontainers when dependencies are missing:
  1. If `TEST_DATABASE_URL` / `TEST_REDIS_URL` / `TEST_RABBITMQ_URL` is configured, or local services are reachable, tests connect to the existing infrastructure.
  2. Otherwise, tests must automatically initialize a testcontainer (e.g., `PostgresContainer("postgres:16", driver="asyncpg")`, Redis, or RabbitMQ) in `conftest.py`.
  3. All database tables must be initialized via `init.sql` (or migrations) and cleanly truncated between test runs.
* **VS Code Integration**:
  Ensure `.vscode/settings.json` is configured to enable pytest auto-discovery and run tests cleanly.

---

## 2. Debugging & Developer Experience (DX)
Every module must provide an immediate, turn-key debugging environment in VS Code and interactive HTTP client workflows.

* **Multi-Service Debugging (`.vscode/launch.json`)**:
  * Individual launch configurations for each service:
    * **FastAPI**: `uvicorn app.main:app --reload --port <PORT>` with `justMyCode: true`.
    * **Celery Worker**: `celery -A services.worker.celery_app:celery_app worker --loglevel=DEBUG -P solo` with `subProcess: true`.
    * **Celery Beat** (when applicable): `celery -A ... beat --loglevel=DEBUG`.
  * **Compound Configuration**: A compound profile (e.g., `"FastAPI + Celery Worker"`) that launches all implied microservices concurrently with `"stopAll": true`.
* **REST Client Workflow (`requests/requests.rest`)**:
  * **Concurrent Generation Mandate**: `requests/requests.rest` must be authored and kept in sync **at the exact same time** endpoints and test suites are developed (never deferred).
  * An interactive file for the VS Code REST Client extension organized into **self-contained test workflows** covering:
    1. System Health Check (`GET /health`).
    2. Happy Path Workflow (Step A: Create resource -> Step B: Inspect pending state -> Step C: Dispatch Celery canvas -> Step D: Poll async state & final memo).
    3. Partial Failure / Degradation Workflow.
    4. Fatal Error & Compensation Workflow.
    5. Idempotency Verification (duplicate dispatch rejection).
  * Use chained REST Client variables (e.g., `{{createApp.response.body.application_id}}`) for zero-manual-copy testing.

---

## 3. Documentation & Architectural Diagrams
Clear architectural diagrams and execution traces must accompany every module.

* **Location**: All architectural documentation and test plans reside in `docs/` (e.g., `docs/TEST_PLAN.md` and `docs/ARCHITECTURE_AND_STANDARDS.md`).
* **Test Plan (`docs/TEST_PLAN.md`)**:
  * Defines the test architecture hierarchy (Layer 1 Unit -> Layer 2 Canvas -> Layer 3 API -> Layer 4 Benchmarks).
  * Comprehensive Test Matrix table specifying: Test ID, Function/File, Fixture/Input, Invariants/Assertions, and Expected Outcome.
  * Red-Green-Refactor TDD roadmap.
* **Mermaid Visualizations**:
  * Use Mermaid flowcharts (`flowchart TD` / `flowchart LR`) for system topologies, layer boundaries, and broker topologies.
  * **Mandatory Sequence Diagrams (`sequenceDiagram`)**:
    * Must cover **all execution paths**:
      * Happy path (API -> DB -> RabbitMQ -> Worker fan-out -> Redis sync barrier -> Callback fan-in -> Persistence).
      * Partial degradation (Result Envelope pattern -> degraded flag -> audit review).
      * Unrecoverable error / Errback compensation (`link_error` -> state machine failure transition -> notification).
      * Idempotency & deduplication rejection paths.
* **Docstrings per Method/Function**:
  * Mandatory Google-style docstrings for **every** module, class, and method/function (including internal helpers and tasks), specifying purpose, args, return type, and raised exceptions.
* **Code Readability & Step-by-Step Block Comments**:
  * Code must be self-documenting and narrative: function names and variables must express domain intent clearly so high-level logic reads like prose.
  * For multi-step, complex, or long functions/methods, partition the body into logical sequential blocks labeled with brief, numbered step comments (e.g., `# 1. Validate payload & preconditions`, `# 2. Check cache / DB state`, `# 3. Dispatch Celery canvas`, `# 4. Persist transaction & audit log`).
  * A developer skimming the file must be able to follow the entire execution flow simply by reading the method calls and step header comments.
  * When clean code alone is not enough—such as non-obvious business invariants, regex parsing, minor-unit financial arithmetic, or Celery barrier synchronization—include concise inline comments explaining the *rationale* ("why"), not merely repeating the code ("what").

---

## 4. FastAPI & API Standards
Every API implementation must adhere to strict asynchronous and robustness patterns:

1. **Async Endpoints as Default**:
   * All API routes must be declared `async def`.
   * Never block the event loop; use SQLAlchemy 2.0 `asyncpg` (`AsyncSession`), async HTTP clients (`httpx.AsyncClient`), and non-blocking I/O.
2. **Development Logger Setup (`app/logging_config.py`)**:
   * Configurable for `INFO` or `DEBUG` level.
   * **Pretty Formatter for Development**:
     - Short timestamp: `datefmt="%H:%M:%S"`.
     - Truncated UUID: First 8 characters of `request_id` (`req_id[:8]`).
     - No verbose HTTP headers if standard fields (`status_code`, `path`, `method`, `duration_ms`) are present.
     - Extra domain attributes formatted concisely as `key=value`.
   * ContextVar propagation: Store `current_request_id: ContextVar[str | None]` to propagate correlation IDs across async calls and Celery task headers.
3. **Centralized Error Handling Middleware (`app/main.py`)**:
   * Provide an `ErrorHandlingMiddleware(BaseHTTPMiddleware)` that:
     - Extracts incoming `X-Request-ID` or generates a new UUID.
     - Sets the `current_request_id` context variable.
     - Measures elapsed request latency (`duration_ms`).
     - Intercepts unhandled exceptions, logs them via `logger.exception("unhandled_request_error")`, and returns a normalized JSON response (`status_code=500`, `{"detail": "internal server error", "request_id": ...}`) to prevent server crashes.
     - Always attaches `X-Request-ID` to response headers.
     - Emits `request_error` on $4xx/5xx$ and `request_complete` on completion.
4. **Pydantic v2 & Strong Validation**:
   * Strictly use Pydantic v2 conventions (`model_config = ConfigDict(from_attributes=True)`).
   * Use `Field(..., description=..., examples=...)` with domain constraints (`gt=0`, `ge=0`, regex patterns).
   * Implement explicit validators using `@field_validator` and `@model_validator(mode="after")`.
5. **Monetary & Numeric Precision**:
   * Any monetary fields or values susceptible to calculation drift must strictly use Python's `Decimal` (never IEEE 754 `float`).
   * Database persistence must use SQL `NUMERIC(14, 2)` or `NUMERIC(18, 4)`.
   * Internal balance and ledger math in workers must execute in **minor units (integer cents)** with explicit rounding (`ROUND_HALF_UP`).
6. **Interactive OpenAPI / Swagger Docs (`/docs`)**:
   * All Pydantic models, request bodies, query parameters, and path variables must define **valid, realistic specimen examples and defaults** using `Field(..., examples=[...])` or `model_config = ConfigDict(json_schema_extra={"examples": [...]})`.
   * When inspecting `/docs` (Swagger UI), clicking **"Try it out" -> "Execute"** must work immediately out of the box with realistic specimen data, without requiring manual JSON editing or triggering $422$ Unprocessable Entity validation errors.

---

## 5. Celery & Distributed Architecture Invariants
When implementing or modifying Celery tasks and APIs:

1. **Strict Broker Safety**:
   * Never pass ORM models, database sessions, file descriptors, or live sockets through Celery task arguments or return values.
   * Tasks must accept strictly **JSON-serializable primitives** (UUID strings, integer IDs, filesystem paths, primitive types).
2. **Canvas Signature Discipline**:
   * Explicitly choose between mutable `.s()` (passes upstream result as first argument) and immutable `.si()` (ignores upstream return values, ideal for audit logs or notifications).
   * Always pair fan-out `chord` groups with a robust callback that handles empty or degraded result sets.
3. **Fault Tolerance & Result Envelopes**:
   * Prefer **Result Envelopes** (`{"status": "ok" | "degraded", "data": {...}, "errors": [...]}`) for non-fatal errors rather than throwing unhandled exceptions that crash chords.
   * Use `link_error` / errbacks to transition applications to failure states when unrecoverable fatal errors occur.
4. **Observability**:
   * Propagate request and correlation IDs across async FastAPI requests and Celery worker task headers via Python `contextvars`.
