# Agent Guidelines & Local Invariants

* **Creation Mask (`umask 022`)**: Always execute commands creating files or directories with `umask 022` (directories `755`, regular files `644`). Never generate `777` or `666` permissions.
* **Granular Micro-Commit Discipline**:
  - All commits must strictly use single-line Conventional Commits (`<type>(<scope>): <summary>`, $\le 72$ chars).
  - Development micro-commits:
    - Requirements: `chore(deps): declare base dependencies in requirements_api.txt and requirements_dev.txt`
    - DDL & Database: `feat(db): declare postgresql 16 relational ddl in init.sql with partial index`
    - AMQP Topology: `feat(amqp): declare kombu exchanges and queues topology in shared/amqp_topology.py`
    - Shared Models: `feat(models): declare domain models in shared/models.py as shared kernel`
    - Shared Schemas: `feat(schemas): declare domain schemas in shared/schemas.py as shared kernel`
    - RabbitMQ Definitions: `chore(rabbitmq): configure pre-loaded rabbitmq topology definitions and vhost`
    - Centralized Docker: `chore(docker): centralize service dockerfiles under docker/ directory`
    - Celery App: `feat(worker): configure celery app with acks_late and lost worker rejection`
    - Celery Tasks: **ONE TASK PER COMMIT** (with localized unit tests)
    - Per API: minimal API skeleton (`/health`, `/ready`), Swagger examples & endpoints.
  - Zero broken execution: each micro-commit must pass syntax, type checking, and its localized unit tests independently.
* **Clean Architecture & Domain-Driven Design (Shared Kernel)**:
  - Database persistence models (`shared/models.py`), Pydantic domain contracts (`shared/schemas.py`), and Kombu AMQP declarations (`shared/amqp_topology.py`) reside strictly in `shared/` as the **Shared Kernel**.
  - **Never place domain models or shared message schemas inside `app/`**. Headless workers must never import from `app` (`from app.models import ...`), ensuring workers stay decoupled from web frameworks and worker Docker builds stay minimal.
  - Dependencies are strictly unidirectional: `app -> shared`, `services/worker -> shared`, `scripts -> shared`.
* **Centralized Docker Packaging (`docker/` Invariant)**:
  - Centralize all container Dockerfiles under `docker/` (`docker/Dockerfile.api`, `docker/Dockerfile.worker`, `docker/Dockerfile.<service>`), leaving workspace root and service directories clean of Dockerfiles.
  - Pre-boot infrastructure configs reside in `docker/<infra>/` (`docker/rabbitmq/definitions.json`, `docker/rabbitmq/rabbitmq.conf`).
* **Modular Documentation & Anti-Bloat Invariant**:
  - Partition documentation across dedicated files: `README.md`, `docs/ARCHITECTURE_AND_STANDARDS.md`, `docs/SEQUENCE_DIAGRAMS.md`, `docs/MILESTONES.md`, `docs/TEST_PLAN.md`, `docs/USE_CASES.md`, and `.agents/milestones/M<N>_<SLUG>.md`.
  - **Dual-Layer Milestone Generation**: Always maintain `docs/MILESTONES.md` (human-facing lifecycle roadmap and compliance matrix) concurrently with `.agents/milestones/M<N>_<SLUG>.md` (agent-facing procedural execution runbooks with explicit scope fences, micro-commit slicing, and verification gates).
  - Anti-Bloat: NEVER duplicate raw SQL (`init.sql`) or Python models in markdown files. Link directly to code files and use visual Mermaid models (`erDiagram`, `classDiagram`, `flowchart`).
* **Zero Backstage File Modification & Anti-Editor Conflict Invariant**:
  - Never open files in the editor or trigger editor tab openings during automated agent operations.
  - Never perform "backstage" modifications (such as running `ruff check --fix` or repeated overwrite edits) after writing a file; always author fully formatted, sorted, and lint-clean code upfront on the first attempt so disk contents never conflict with open editor buffers.
  - Workspace configuration (`.vscode/settings.json`) must strictly maintain `"files.autoSave": "off"` and `"editor.formatOnSave": false` to prevent editor buffers from dirtying or overwriting on-disk files.
* **Debugging & Just-in-Time Debug Configurations**:
  - **Progressive Debug Config Generation**: In `.vscode/launch.json`, generate debug configurations strictly for services and entry points that currently exist and are suitable to be debugged at that point in development. Never generate dangling or speculative configurations pointing to non-existent applications, files, or entry points.
  - **Compound Multi-Service Configurations**: When several services or architectural layers (e.g., FastAPI gateway, Celery worker, simulator APIs) are complete and should be run together, generate compound debug configurations (`compounds` with `"stopAll": true`) to launch and debug them all concurrently.
  - **Milestone Runbook Invariant**: For any implementation milestone that introduces or updates a runnable service, worker, API, simulator, or harness, `.vscode/launch.json` MUST be included in the in-scope files and scheduled as a dedicated micro-commit (`chore(debug): ...`).
  - **Interactive REST Scenarios**: Self-contained test scenarios in `requests/requests.rest` (generated concurrently with endpoints and tests).

