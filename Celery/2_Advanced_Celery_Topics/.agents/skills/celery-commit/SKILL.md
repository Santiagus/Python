---
name: celery-commit
description: >-
  Enforce atomic, granular, and non-breaking git commits for Celery and distributed backend modules.
  Use this skill when staging, organizing, generating, or proposing git commits to ensure changes are
  partitioned into minimal cohesive units without breaking test execution, type checking, or system stability.
---

# Celery Atomic & Granular Commit Standards

This skill defines the standards and procedural rules for generating small, atomic, and self-contained git commits across Celery and distributed backend codebases.

---

## 1. Core Invariants

0. **Mandatory Review Prior to Commit & Push (Strict Non-Negotiable Invariant)**:
   - Any code, test, documentation, or configuration change is strictly subject to user review prior to commit.
   - Running `git commit` or `git push` without explicit user confirmation and authorization is **strictly forbidden** under all circumstances.
   - Always present the proposed changes, file diffs, and test/lint validation results to the user, and await their explicit instruction before running any commit or push command.

1. **Granular & Cohesive Scope**:
   - Commits must be kept as small as possible, focused strictly on a single cohesive architectural concern or file set (1–3 files maximum: code file + localized unit test).
   - **Monolithic commits are strictly forbidden**. Bundling models, tasks, API endpoints, configurations, container manifests, test suites, and documentation all at once violates auditability and git bisectability.
   - Any commit staging 4 or more files must be scrutinized and partitioned into cohesive micro-commits.

2. **One-Line Commit Message Mandate**:
   - Commit messages must strictly consist of a single concise Conventional Commit line: `<type>(<scope>): <imperative summary>` ($\le 72$ characters).
   - **Do not author multi-line bodies or bullet points** for atomic commits. If a commit feels like it requires multiple bullet points to explain disparate actions, it is an explicit signal that the commit bundles too many concerns and must be split.

3. **Development Micro-Commit Slicing Matrix**:
   Partition development strictly into independent, cohesive micro-commits:
   - `chore(deps)`: Dependency manifests (`requirements_api.txt`, `requirements_dev.txt`, `services/*/requirements.txt`).
   - `feat(db)`: Database DDL (`init.sql`) and database configuration (committed with its dedicated DDL test).
   - `chore(db)`: Database container Dockerfile or engine parameters.
   - `feat(amqp)`: Kombu AMQP 0-9-1 topology (`shared/amqp_topology.py`) (committed with its dedicated topology test).
   - `chore(rabbitmq)`: RabbitMQ pre-loaded topology definitions (`definitions.json`, `rabbitmq.conf`).
   - `chore(rabbitmq)`: RabbitMQ Dockerfile or broker container manifest.
   - `feat(worker)`: Celery worker application configuration (`celery_app.py`) (committed with its configuration test).
   - `feat(worker)`: Individual Celery task (**STRICTLY ONE TASK PER COMMIT**, committed with its dedicated unit test).
   - `chore(worker)`: Celery worker Dockerfile and runtime entrypoint.
   - Per API Gateway / Mock Service (e.g. `app/`, `services/bank_simulator_api/`):
     - `feat(api)`: Minimal API skeleton with `/health` and `/ready` probes (committed with health test).
     - `feat(models)`: Domain database models definition (committed with model test).
     - `feat(models)`: Model validations and data constraints definition.
     - `feat(schemas)`: Pydantic v2 request/response schemas (committed with schema test).
     - `feat(api)`: API routes and Swagger/OpenAPI documentation with realistic examples.
   - `chore(orchestration)`: Multi-container orchestration (`docker-compose.yml`) (committed with orchestration test).

4. **Documentation Micro-Commit Slicing Matrix**:
   Partition documentation across dedicated, specialized files rather than creating monolithic, bloated markdown documents:
   - `docs(proposal)`: Project proposal added to `README.md`.
   - `docs(arch)`: System architecture and topology specification in `docs/ARCHITECTURE_AND_STANDARDS.md`.
   - `docs(use-cases)`: Business workflows and failure recovery scenarios in `docs/USE_CASES.md`.
   - `docs(test-plan)`: Test strategy, test matrix table, and execution plan in `docs/TEST_PLAN.md`.
   - `docs(milestones)`: Detailed milestone roadmap in `docs/MILESTONES.md` and agent execution runbooks in `.agents/milestones/`.
   - `docs(diagrams)`: Comprehensive distributed sequence diagrams across all execution paths in `docs/SEQUENCE_DIAGRAMS.md`.

5. **Documentation Anti-Bloat & Single Source of Truth (SSOT) Invariant**:
   - Never copy-paste raw implementation code (`init.sql`, Pydantic models, Kombu definitions) into markdown documentation.
   - Use direct clickable markdown links to source files (`[init.sql](...)`).
   - Use visual Mermaid models (`erDiagram` for schemas, `classDiagram` for models, `flowchart` for topology) instead of redundant code blocks.

6. **Zero-Broken-Execution Invariant**:
   - Every individual micro-commit must be functionally self-contained and working.
   - **Never commit broken intermediate states**, unresolved imports, dangling debug configurations, failing tests, or invalid type annotations.
   - Every commit in a sequence must independently pass syntax validation, type checking (`mypy`), linting (`ruff`), and its localized unit tests (`pytest`).

---

## 2. Commit Slicing Procedure

When preparing commits for development or documentation:

### Step 1: Stage One Cohesive Slice (1–3 Files Max)
Identify the next logical component in the dependency chain (e.g., `init.sql` + `tests/unit/test_init_sql.py`) and stage only those files.

### Step 2: Verify Isolated Execution
Run the localized test suite to guarantee green execution:
```bash
.venv/bin/pytest tests/unit/test_init_sql.py
```

### Step 3: Propose Single-Line Commit Message
Present the proposed staged files, diff summary, and single-line Conventional Commit message to the user:
```text
Proposed Commit:
feat(db): declare postgresql 16 relational ddl in init.sql with partial index
Files: init.sql, tests/unit/test_init_sql.py
```
Await explicit user confirmation prior to executing `git commit`.

