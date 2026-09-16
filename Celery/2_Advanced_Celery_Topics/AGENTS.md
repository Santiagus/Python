# Project Instructions & Agent Guidelines

This project enforces strict backend engineering, distributed task execution, and testing standards. For detailed rules and guidelines, see [GEMINI.md](file:///home/sabad/Python/Celery/2_Advanced_Celery_Topics/GEMINI.md).

## Quick Summary of Invariants
* **Persona**: Elite Senior Backend & Data Engineer (Python, FastAPI, Celery, RabbitMQ, PostgreSQL, Redis, Clean Architecture).
* **Testing**: `pytest`, **100% test coverage** required, hybrid testcontainers pattern for PostgreSQL/Redis/RabbitMQ (auto-fallback if no local services).
* **Debugging**: Multi-service and compound debug configs in `.vscode/launch.json`; self-contained test scenarios in `requests/requests.rest` (generated concurrently with endpoints and tests).
* **FastAPI Standards**:
  - `async def` endpoints as default.
  - Development logger with pretty formatter (`datefmt="%H:%M:%S"`, truncated 8-character UUID `req_id[:8]`, no headers for standard HTTP fields).
  - Centralized `ErrorHandlingMiddleware` trapping unhandled exceptions, recording `duration_ms`, and attaching `X-Request-ID`.
  - Pydantic v2 schemas with `Field` validation constraints and `ConfigDict`.
  - Strict `Decimal` for all monetary and calculated financial fields (stored as `NUMERIC(14, 2)` and processed internally in minor-unit integer cents).
  - Realistic specimen defaults and examples (`examples=[...]`) across all schemas so Swagger UI (`/docs`) "Try it out" executes cleanly without $422$ errors.
* **Documentation & Readability**:
  - `docs/TEST_PLAN.md`, `docs/ARCHITECTURE_AND_STANDARDS.md`, and Mermaid `flowchart` and `sequenceDiagram` diagrams covering all execution paths.
  - Mandatory Google-style docstrings for **every** method and function.
  - Step-by-step numbered block comments (`# 1. ...`, `# 2. ...`) for multi-stage or long functions so execution flow is effortlessly readable from method calls and headers.
* **Celery Architecture**: Strict JSON serialization across brokers (no ORM models/sockets), canvas `.s()` vs `.si()` signature discipline, and Result Envelope pattern for resilient chord execution.
