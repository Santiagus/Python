# Agent Guidelines & Local Invariants

* **Creation Mask (`umask 022`)**: Always execute commands creating files or directories with `umask 022` (directories `755`, regular files `644`). Never generate `777` or `666` permissions.
* **Granular Micro-Commit Discipline**:
  - All commits must strictly use single-line Conventional Commits (`<type>(<scope>): <summary>`, $\le 72$ chars).
  - Development micro-commits:
    - Requirements: `chore(deps): declare base dependencies in requirements_api.txt and requirements_dev.txt`
    - DDL & Database: `feat(db): declare postgresql 16 relational ddl in init.sql with partial index`
    - DB Container: `chore(db): configure postgresql engine parameters and container specification`
    - AMQP Topology: `feat(amqp): declare kombu exchanges and queues topology in shared/amqp_topology.py`
    - RabbitMQ Definitions: `chore(rabbitmq): configure pre-loaded rabbitmq topology definitions and vhost`
    - Celery App: `feat(worker): configure celery app with acks_late and lost worker rejection`
    - Celery Tasks: **ONE TASK PER COMMIT** (with localized unit tests)
    - Celery Dockerfile: `chore(worker): author headless celery worker dockerfile and entrypoint`
    - Per API: minimal API skeleton (`/health`, `/ready`), models definition, models validations, schemas definition, Swagger examples & endpoints.
  - Zero broken execution: each micro-commit must pass syntax, type checking, and its localized unit tests independently.
* **Modular Documentation & Anti-Bloat Invariant**:
  - Partition documentation across dedicated files: `README.md`, `docs/ARCHITECTURE_AND_STANDARDS.md`, `docs/SEQUENCE_DIAGRAMS.md`, `docs/MILESTONES.md`, `docs/TEST_PLAN.md`, `docs/USE_CASES.md`.
  - Anti-Bloat: NEVER duplicate raw SQL (`init.sql`) or Python models in markdown files. Link directly to code files and use visual Mermaid models (`erDiagram`, `classDiagram`, `flowchart`).
