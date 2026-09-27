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
   - Commits must be kept as small as possible, focused on a single cohesive architectural or domain concern.
   - Avoid monolithic commits that bundle models, tasks, API endpoints, configurations, test suites, and documentation all at once.
   - Partition changes logically across architectural boundaries:
     - **Database / Schema**: DDL migrations, SQLAlchemy ORM models, check constraints.
     - **Domain Tasks & Locks**: Worker tasks, distributed mutexes, canvas workflows.
     - **Scheduler & Beats**: Periodic crontab schedules, leader election, failover hooks.
     - **API / Control Plane**: Pydantic schemas, middleware, producer dispatchers, FastAPI routes.
     - **Developer Experience & Tooling**: `.vscode/launch.json` compound profiles, `requests/requests.rest` workflows.
     - **Documentation**: Architectural audits, test plans, Mermaid diagrams.
     - **Test Suites**: Unit and integration tests accompanying their corresponding domain components.

2. **Zero-Broken-Execution Invariant**:
   - Every individual commit must be functionally self-contained and working.
   - **Never commit broken intermediate states**, unresolved imports, dangling debug configurations, failing tests, or invalid type annotations.
   - Every commit in a sequence must independently pass:
     - Syntax and imports validation.
     - Static type checking (`mypy --ignore-missing-imports`).
     - Linting and formatting (`ruff check`, `ruff format --check`).
     - Unit / integration test suite (`pytest`).

3. **Conventional Commits & Semantic Prefixes**:
   - Follow standard Conventional Commits syntax:
     - `feat(<module>): ...` for new features, tasks, endpoints, or models.
     - `fix(<module>): ...` for bug fixes, deadlocks, race conditions, or schema patches.
     - `test(<module>): ...` for dedicated test additions or fixture refactors.
     - `docs(<module>): ...` for architecture guides, test plans, and Mermaid diagrams.
     - `chore(<module>): ...` for CI/CD runners, virtualenv manifests, or editor configs.

---

## 2. Commit Slicing Procedure

When preparing commits for a completed milestone or complex feature:

### Step 1: Group Files by Architectural Tier
Inspect `git status` and cluster modified or untracked files into logical, cohesive tiers:
1. `README.md` + `docs/ARCHITECTURE_AND_STANDARDS.md` + `docs/TEST_PLAN.md` (Milestone 1: proposal, architecture, and initial test matrix covering all use cases).
2. Database DDL migrations (`init.sql`), container definitions, and SQLAlchemy ORM models.
3. Domain worker tasks (`services/worker/tasks/`), Celery canvas, and unit tests (`tests/unit/`) with progressive `pyproject.toml` pytest config and worker launch config in `.vscode/launch.json`.
4. API schemas, middlewares, producer dispatchers, FastAPI routes, matching API debug configs, and matching `requests/requests.rest` workflows with integration tests (`tests/integration/`).
5. Live multi-process distributed E2E test suite (`tests/e2e/test_live_e2e.py`) and capacity benchmarks (`tests/benchmarks/`, `scripts/benchmark_*.py`) as the strictly final development steps.

### Step 2: Verify Incremental Buildability
Ensure that staging Tier 1 does not rely on uncommitted symbols from Tier 2, or stage them together if strictly interdependent. Each commit must leave the repository in a green, working state.

### Step 3: Author Concise, Focused Commit Messages
Format each commit message with:
- A concise summary line ($\le 72$ chars).
- 2–4 bullet points detailing specific changes and invariants preserved.

