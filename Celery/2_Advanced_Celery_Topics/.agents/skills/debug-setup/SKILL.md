---
name: celery-debug-setup
description: >-
  Configure or update per-project VS Code debug environments (.vscode/launch.json,
  .vscode/settings.json), FastAPI logging and error handling middlewares, and
  self-contained REST Client test suites (requests/requests.rest). Use this skill when
  setting up a new Celery module, configuring debugging for APIs and Celery workers,
  or building REST test files concurrently with endpoints and tests.
---

# Celery Module Debug, FastAPI Standards & REST Setup Runbook

When working with individual project folders (such as `03_routing_and_capacity`, `04_scheduling`, etc.), VS Code requires `.vscode/` configurations to reside inside the opened folder root. This skill provides the exact templates and procedures to scaffold `.vscode/`, FastAPI logging/middleware, and `requests/requests.rest`.

---

## 1. VS Code Debugging (`.vscode/launch.json`)

Place this file at `<module_folder>/.vscode/launch.json`. Adjust module paths and environment ports as needed.

> [!IMPORTANT]
> **Progressive Just-in-Time Generation**:
> Only include launch configurations for services and entry points that actually exist and are suitable to be debugged at that stage of development. Do not generate dangling debug configurations pointing to non-existent applications (e.g., omit the FastAPI configuration if the module does not have or has not yet implemented the FastAPI app).
> When several services/layers (e.g., API gateway, Celery worker, Celery beat, simulator APIs) are complete and intended to be run together, generate a compound debug configuration (`compounds` with `"stopAll": true`) to launch and debug them all concurrently.

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python Debugger: FastAPI",
            "type": "debugpy",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8010",
                "--reload"
            ],
            "cwd": "${workspaceFolder}",
            "env": {
                "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5433/service_db",
                "REDIS_URL": "redis://localhost:6380/0",
                "RABBITMQ_URL": "amqp://guest:guest@localhost:5673//",
                "ENVIRONMENT": "development",
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "pretty"
            },
            "justMyCode": true
        },
        {
            "name": "Python Debugger: Celery Worker",
            "type": "debugpy",
            "request": "launch",
            "module": "celery",
            "args": [
                "-A",
                "services.worker.celery_app:celery_app",
                "worker",
                "--loglevel=DEBUG",
                "-P",
                "solo"
            ],
            "cwd": "${workspaceFolder}",
            "env": {
                "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5433/service_db",
                "REDIS_URL": "redis://localhost:6380/0",
                "RABBITMQ_URL": "amqp://guest:guest@localhost:5673//",
                "ENVIRONMENT": "development",
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "pretty"
            },
            "justMyCode": true,
            "subProcess": true
        }
    ],
    "compounds": [
        {
            "name": "FastAPI + Celery Worker",
            "configurations": [
                "Python Debugger: FastAPI",
                "Python Debugger: Celery Worker"
            ],
            "stopAll": true
        }
    ]
}
```

---

## 2. VS Code Test Settings (`.vscode/settings.json`)

Place this file at `<module_folder>/.vscode/settings.json`:

```json
{
    "python.testing.pytestArgs": [
        "tests"
    ],
    "python.testing.unittestEnabled": false,
    "python.testing.pytestEnabled": true
}
```

---

## 3. FastAPI Development Logger (`app/logging_config.py`)

Development logs must be clean, readable, and structured without unnecessary header clutter:
- Short timestamp: `%H:%M:%S`.
- Truncated UUID: First 8 characters of `request_id` (`req_id[:8]`).
- No verbose headers if standard HTTP fields (`method`, `path`, `status_code`, `duration_ms`) are present.
- ContextVar tracking for asynchronous request isolation.

```python
"""Runtime logging configuration for structured and pretty request logging."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from pythonjsonlogger.json import JsonFormatter

current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class RequestContextFilter(logging.Filter):
    """Inject current request ID from async context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if (req_id := current_request_id.get()) and not hasattr(record, "request_id"):
            record.request_id = req_id
        return True


class PrettyFormatter(logging.Formatter):
    """Compact, human-readable log formatter for development."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")}

        # 1. Truncated request ID (8 chars)
        req_id = str(extras.pop("request_id", ""))[:8]

        # 2. Extract standard HTTP fields without raw header noise
        http = [str(extras.pop(k)) for k in ("method", "path", "status_code") if extras.get(k)]
        if dur := extras.pop("duration_ms", None):
            http.append(f"{dur}ms")

        # 3. Format remaining domain extra fields
        domain = [f"{k}={v!r}" if " " in str(v) else f"{k}={v}" for k, v in extras.items() if v is not None]

        parts = ([req_id] if req_id else []) + http + domain
        base = super().format(record)
        if parts:
            first, *rest = base.split("\n", 1)
            return f"{first} {' '.join(parts)}" + (f"\n{rest[0]}" if rest else "")
        return base


def configure_logging(level: str = "INFO", log_format: str = "pretty") -> None:
    """Configure root logger to emit pretty console output or structured JSON."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        PrettyFormatter() if log_format == "pretty" else JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.root.handlers = [handler]
    logging.root.setLevel(level)
```

---

## 4. Centralized Error Handling Middleware (`app/main.py`)

Every FastAPI application must implement an `ErrorHandlingMiddleware` to trap unexpected exceptions and prevent unhandled server crashes:

```python
class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Attach request IDs, record duration, and trap unhandled exceptions."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        token = current_request_id.set(request_id)
        started = time.perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "unhandled_request_error",
                    extra={"request_id": request_id, "path": request.url.path},
                )
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "internal server error", "request_id": request_id},
                )

            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers["X-Request-ID"] = request_id

            if response.status_code >= 400 and not getattr(request.state, "error_logged", False):
                logger.warning(
                    "request_error",
                    extra={
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )

            logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            current_request_id.reset(token)
```

---

## 5. Pydantic v2, Financial Decimal Discipline & OpenAPI Valid Defaults

- All request/response models must use Pydantic v2 (`ConfigDict`, `Field`).
- Monetary and financial fields must be strictly typed as `Decimal` (never `float`).
- **OpenAPI /docs Pre-filled Specimen Data**: Provide **valid, realistic specimen values** via `Field(..., examples=[...])` or `json_schema_extra`. When visiting `/docs`, clicking **"Try it out" -> "Execute"** should succeed immediately without manual JSON editing or $422$ validation errors.

```python
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field

class FacilityApplication(BaseModel):
    """Commercial credit facility request with pre-filled Swagger specimens."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "company_name": "Apex Fintech Dynamics Inc.",
                    "applicant_name": "JANE DOE",
                    "requested_amount": "250000.00",
                    "manifest": {
                        "bank_statement": "tests/fixtures/clean_4pages/bank_statement_4pages.pdf",
                        "kyc_id": "tests/fixtures/clean_4pages/kyc_executive_id.jpg",
                        "tax_filing": "tests/fixtures/clean_4pages/tax_filing_irs1120.pdf",
                    },
                }
            ]
        },
    )

    company_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Legal commercial entity name",
        examples=["Apex Fintech Dynamics Inc."],
    )
    applicant_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Authorized officer full name",
        examples=["JANE DOE"],
    )
    requested_amount: Decimal = Field(
        ...,
        gt=0,
        description="Requested facility amount in USD",
        examples=[Decimal("250000.00")],
    )
    manifest: dict[str, str] | None = Field(
        default=None,
        description="Optional mapping of document types to specimen file paths",
        examples=[
            {
                "bank_statement": "tests/fixtures/clean_4pages/bank_statement_4pages.pdf",
                "kyc_id": "tests/fixtures/clean_4pages/kyc_executive_id.jpg",
                "tax_filing": "tests/fixtures/clean_4pages/tax_filing_irs1120.pdf",
            }
        ],
    )
```

---

## 6. Concurrent REST Client Suite (`requests/requests.rest`)

> [!IMPORTANT]
> **Concurrent Generation Mandate**: `requests/requests.rest` must be generated and updated **at the exact same time** as the FastAPI endpoints and test suite.

Organize the file into **self-contained test workflows** using named requests and variable chaining:

```http
# ==============================================================================
# Service REST Client Test Suite
# ==============================================================================
# Organized in self-contained workflows:
# Step A: POST resource (captures ID in named variable)
# Step B: GET resource status (validates pending state)
# Step C: Trigger asynchronous processing
# Step D: Poll completed state and inspect decision memo
# ==============================================================================

@clientUrl = http://localhost:8010
@baseUrl = {{clientUrl}}
@apiPrefix = /api/v1

# ==============================================================================
# 0. HEALTH CHECK
# ==============================================================================

###
# 0.1 Service Health Check
GET {{baseUrl}}/health


# ==============================================================================
# 1. HAPPY PATH WORKFLOW
# ==============================================================================

###
# 1.1 Create Resource
# @name createJob
POST {{baseUrl}}{{apiPrefix}}/jobs
Content-Type: application/json

{
  "title": "Batch Processing Job",
  "priority": "high",
  "requested_amount": 250000.00,
  "payload": {
    "items_count": 100
  }
}

###
# 1.2 Inspect Initial Status
GET {{baseUrl}}{{apiPrefix}}/jobs/{{createJob.response.body.job_id}}

###
# 1.3 Dispatch Processing
POST {{baseUrl}}{{apiPrefix}}/jobs/{{createJob.response.body.job_id}}/dispatch
Content-Type: application/json

###
# 1.4 Poll Final Result
GET {{baseUrl}}{{apiPrefix}}/jobs/{{createJob.response.body.job_id}}
```
