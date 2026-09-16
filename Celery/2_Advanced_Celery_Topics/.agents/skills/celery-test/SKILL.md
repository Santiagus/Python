---
name: celery-test
description: >-
  Generate comprehensive pytest unit and integration tests with 100% statement coverage,
  mocking external dependencies, using fixtures, and implementing hybrid testcontainers
  (PostgreSQL, Redis, RabbitMQ). Use this skill when asked to write tests, add test suites,
  configure testcontainers, or verify 100% test coverage.
---

# Celery & Backend Pytest Test Suite Generation

This skill guides the construction and execution of a production-grade testing suite with a hard requirement of **100% statement coverage** across all Python modules.

## Architecture of Test Hierarchy

Tests must be partitioned into distinct layers:

1. **Unit Tests (`tests/unit/`)**:
   - Focus: Pure functions, domain calculations, currency/minor-unit math, Pydantic v2 schema validators, internal task processors.
   - Validation & Error Tests: Verify that non-positive Decimal amounts or invalid types trigger `ValidationError` / HTTP 422.
   - Isolation: Zero external services. Mock all external dependencies (database, Redis, Celery broker, HTTP clients) using `unittest.mock` (`AsyncMock`, `patch`, `MagicMock`).
2. **Integration Tests (`tests/integration/`)**:
   - Focus: Database queries (SQLAlchemy asyncpg), transactional rollbacks, database constraint enforcement, and FastAPI routes.
   - FastAPI Client: Test `async def` endpoints using `httpx.AsyncClient` with `ASGITransport(app=app)`.
   - Middleware Verification: Test that `ErrorHandlingMiddleware` intercepts unhandled exceptions, returns normalized 500 JSON, attaches `X-Request-ID`, and records `duration_ms`.
   - Dependencies: Real PostgreSQL instance (local or testcontainer).
3. **Canvas & Workflow Tests (`tests/test_canvas_workflows.py`, `tests/test_partial_failure.py`)**:
   - Focus: Celery canvas chains, chords, signatures (`.s()` vs `.si()`), errbacks (`link_error`), and Result Envelope handling.
   - Isolation/Execution: Run either with `celery_app.conf.task_always_eager = True` or mock chord barriers to test logic deterministically.
4. **Live E2E Tests (`tests/test_live_e2e.py`)**:
   - Focus: End-to-end multi-service verification with running workers and message brokers.

---

## Hybrid Testcontainer Pattern (`conftest.py`)

Every test suite must support a **hybrid database and service lifecycle**:
- If environment variables point to existing services (e.g. `TEST_DATABASE_URL`), connect directly.
- If no environment variable is provided, automatically launch an ephemeral testcontainer.

### Reference Implementation: PostgreSQL Async Testcontainer
```python
import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

MODULE_ROOT = Path(__file__).resolve().parent.parent

# Disable Ryuk for socket resilience in container/WSL2 environments
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer | None, None, None]:
    """Launch a PostgreSQL 16 testcontainer for the test session if no local DB specified."""
    if os.getenv("TEST_DATABASE_URL"):
        yield None
        return
    try:
        with PostgresContainer("postgres:16", driver="asyncpg") as container:
            yield container
    except Exception:
        yield None

@pytest.fixture(scope="session")
async def test_database_url(postgres_container: PostgresContainer | None) -> str:
    """Initialize schema using init.sql against testcontainer or local DB and return async DB URL."""
    if os.getenv("TEST_DATABASE_URL"):
        db_url = os.environ["TEST_DATABASE_URL"]
    elif postgres_container is not None:
        db_url = postgres_container.get_connection_url(driver="asyncpg")
    else:
        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5433/test_db"

    # Execute DDL from init.sql
    init_sql_path = MODULE_ROOT / "init.sql"
    if init_sql_path.exists():
        with open(init_sql_path) as f:
            ddl = f.read()
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            raw_conn = await conn.get_raw_connection()
            await raw_conn.driver_connection.execute(ddl)
        await engine.dispose()
    return db_url

@pytest.fixture
async def db_session(test_database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated transactional async database session with automatic cleanup."""
    engine = create_async_engine(test_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()

@pytest.fixture
async def async_client(test_database_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTPX AsyncClient wired to the test FastAPI app."""
    from app.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

---

## Step-by-Step Procedure for Creating Tests

1. **Audit Code Under Test**:
   - Identify all conditionals, exceptions, edge cases, and external calls.
   - List required fixtures: test payloads, mock database sessions, error manifests.
2. **Implement Unit Tests First**:
   - Create unit tests verifying positive and negative validation.
   - Verify zero floating-point math; use exact `Decimal` and integer minor units (cents).
   - Test Pydantic model validation failures (e.g., negative or zero facility amounts).
3. **Implement Integration & API Tests**:
   - Test async API endpoints via `httpx.AsyncClient`.
   - Test `ErrorHandlingMiddleware` exception-trapping and `X-Request-ID` propagation.
4. **Implement Workflow / Canvas Tests**:
   - Test sequential `.s()` piping vs `.si()` argument dropping.
   - Test chord barrier: verify callback processes list of results.
   - Test degraded envelopes: verify non-fatal errors route gracefully to review.
   - Test errbacks: verify `link_error` triggers compensating state updates.
5. **Synchronous REST Client Generation**:
   - Ensure `requests/requests.rest` is created/updated in lockstep with new endpoints and tests.
6. **Run Pytest with Coverage**:
   ```bash
   pytest --cov=app --cov=services/worker --cov-report=term-missing --cov-fail-under=100
   ```
7. **Close Coverage Gaps**:
   - Inspect missing line numbers reported by `--cov-report=term-missing`.
   - Add targeted test cases to trigger every branch, validation check, and error handler until 100% statement coverage is achieved.
