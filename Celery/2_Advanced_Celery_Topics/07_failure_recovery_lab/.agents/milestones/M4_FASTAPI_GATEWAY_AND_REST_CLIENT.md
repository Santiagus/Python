# Milestone 4: FastAPI Ingestion Gateway, Dispatcher & REST Client Suite

> **Module**: `07_failure_recovery_lab`  
> **Milestone**: M4  
> **Status**: Ready for Execution (**Next**)  
> **Reference SSOT**: [docs/ARCHITECTURE_AND_STANDARDS.md](../../docs/ARCHITECTURE_AND_STANDARDS.md) | [docs/SEQUENCE_DIAGRAMS.md](../../docs/SEQUENCE_DIAGRAMS.md)

This specification defines the agent execution runbook for Milestone 4.

---

## 1. Scope Boundary & Fences

* **In-Scope Files (Allowed to create / modify)**:
  - `app/main.py` (FastAPI application factory, lifespan pre-warming, route registration)
  - `app/routes/` (`wires.py`, `health.py`)
  - `app/middlewares/` (`correlation.py`, `error_handling.py`)
  - `app/dispatcher.py` (Kombu AMQP producer with publisher confirms)
  - `requests/requests.rest` (self-contained interactive VS Code REST Client test scenarios)
  - `tests/unit/test_dispatcher.py`
  - `tests/unit/test_middlewares.py`
  - `tests/unit/test_api_routes.py`

* **Out-of-Scope Files (Strictly forbidden to modify in M4)**:
  - `scripts/chaos_harness.py` (Chaos harness — reserved for **Milestone 5**)
  - `tests/integration/` (Chaos failure injection tests — reserved for **Milestone 5**)
  - `tests/e2e/`, `tests/benchmarks/` (Live multi-process verification — reserved for **Milestone 6**)

---

## 2. Technical Contracts & Invariants

1. **Zero-Refresh Response Generation**:
   - Pre-generate UUIDv4 primary keys and UTC timestamps in the application layer.
   - Do NOT execute `await session.refresh()` on high-throughput write endpoints.
2. **FinTech In-Flight State Visibility (No 404 Black Hole)**:
   - On `POST /api/v1/wires`, immediately insert record with `status="processing"`.
   - Dispatch Celery task to RabbitMQ with publisher confirms (`confirm_delivery=True`).
   - Subsequent `GET /api/v1/wires/{id}` must immediately return `200 OK` with `status: "processing"`.
3. **Correlation ID Propagation**:
   - Extract incoming `X-Request-ID` or generate new truncated 8-character UUID.
   - Inject into Kombu AMQP message headers and response headers.
4. **Interactive REST Scenarios (`requests/requests.rest`)**:
   - Provide runnable HTTP requests for all endpoints with realistic specimen payloads.

---

## 3. Ordered Micro-Commit Execution Sequence

| Step | Single-Line Conventional Commit ($\le 72$ chars) | Target Files | Dedicated Test File |
| :---: | :--- | :--- | :--- |
| **1** | `feat(api): implement correlation and error handling middlewares` | `app/middlewares/` | `tests/unit/test_middlewares.py` |
| **2** | `feat(amqp): implement reliable kombu dispatcher with publisher confirms` | `app/dispatcher.py` | `tests/unit/test_dispatcher.py` |
| **3** | `feat(api): implement wire ingestion routes with in-flight visibility` | `app/routes/wires.py`, `app/main.py` | `tests/unit/test_api_routes.py` |
| **4** | `chore(rest): author interactive scenario test suite in requests.rest` | `requests/requests.rest` | `tests/unit/test_requests_rest.py` |

---

## 4. Verification & Acceptance Gates

```bash
# 1. Unit tests & 100% statement coverage
.venv/bin/pytest tests/unit/ -v --cov=app --cov-report=term-missing --cov-fail-under=100

# 2. Static type safety & linter
.venv/bin/mypy app
.venv/bin/ruff check app
```
