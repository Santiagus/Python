---
name: celery-doc
description: >-
  Generate clear Google-style docstrings, architecture documentation, test plans, and
  comprehensive Mermaid diagrams (including sequence diagrams covering all execution paths).
  Use this skill when asked to write documentation, create architecture notes, generate
  test plans, or produce Mermaid charts.
---

# Celery Documentation & Architectural Visualization

This skill guides the creation of production-grade documentation, test plans (`docs/TEST_PLAN.md`), architectural audits (`docs/ARCHITECTURE_AND_STANDARDS.md`), and Mermaid diagrams.

---

## 1. Docstring Standards (Google Style)
Every module, class, and public function must have Google-style docstrings clearly explaining purpose, arguments, return values, and raised exceptions:

```python
def process_ledger_entry(amount_cents: int, transaction_type: str) -> dict[str, Any]:
    """Execute minor-unit balance adjustment for a single ledger record.

    Validates that the transaction amount is positive and calculates the resulting
    ledger impact using exact integer arithmetic to avoid IEEE 754 float drift.

    Args:
        amount_cents: Transaction magnitude in minor units (integer cents).
        transaction_type: One of 'credit' or 'debit'.

    Returns:
        A dictionary containing the parsed ledger delta and updated status.

    Raises:
        ValueError: If amount_cents is non-positive or transaction_type is unknown.
    """
```

---

## 2. Code Readability & Step-by-Step Block Comments
When methods or functions contain multiple logical steps or when clean code alone cannot fully convey non-obvious domain decisions:

1. **Docstring per Method**: Every function, method, and internal task must have a Google-style docstring.
2. **Self-Documenting Prose**: Use expressive domain names so high-level logic reads like prose.
3. **Sequential Step Comments**: Partition complex or multi-stage functions into numbered blocks (`# 1. ...`, `# 2. ...`). A developer skimming the file must be able to grasp the whole flow just from method calls and step comments.

### Pattern Example:
```python
async def ingest_credit_dossier(
    session: AsyncSession,
    application_id: UUID,
    manifest: dict[str, str],
) -> DossierSubmitResponse:
    """Validate incoming application dossier and orchestrate Celery canvas execution.

    Args:
        session: Active async database session.
        application_id: Unique application identifier.
        manifest: Mapping of document types to staged filesystem paths.

    Returns:
        DossierSubmitResponse confirming ingestion and Celery task dispatch.

    Raises:
        HTTPException: If application is not found or already in progress.
    """
    # 1. Validate application exists and state allows ingestion
    app_record = await _get_application_or_404(session, application_id)
    if app_record.status != "pending":
        raise HTTPException(status_code=409, detail="Application already submitted")

    # 2. Persist registered documents and partition pages in DB
    registered_docs = await _persist_dossier_manifest(session, application_id, manifest)

    # 3. Assemble distributed Celery canvas (Chord: parallel processors -> aggregation)
    canvas = build_underwriting_canvas(application_id, registered_docs)

    # 4. Dispatch workflow to RabbitMQ with fatal-error errback
    async_result = canvas.apply_async(link_error=handle_workflow_failure.s(str(application_id)))

    # 5. Transition state to 'processing' and commit transaction
    app_record.status = "processing"
    await session.commit()

    return DossierSubmitResponse(
        application_id=str(application_id),
        workflow_id=async_result.id,
        status="processing",
    )
```

---

## 3. Test Plan Generation (`docs/TEST_PLAN.md`)
Every module requires a formal `docs/TEST_PLAN.md` containing:
1. **Test Architecture & Layer Hierarchy**: Visualized with `flowchart TD` showing L1 Unit -> L2 Canvas -> L3 API -> L4 Benchmarks.
2. **Comprehensive Test Matrix Table**:
   | Test ID | Test Function / File | Fixture Input | Invariants & Assertions | Expected Outcome |
   | :--- | :--- | :--- | :--- | :--- |
   | `TC-01` | `tests/test_canvas.py` | Clean sample | Assert all chord header tasks succeed and callback synthesizes result | Status "approved" |
3. **TDD Execution Sequence**: Clear Red-Green-Refactor roadmap with instructions for running the test suite.

---

---

## 4. Modular Documentation Architecture & Anti-Bloat Standards

To prevent unmaintainable monolithic documents and eliminate drift, documentation is strictly partitioned into dedicated single-concern files:

| Documentation File | Dedicated Purpose & Scope | Anti-Bloat Invariant |
| :--- | :--- | :--- |
| `README.md` | Executive overview, problem statement, architecture snapshot, quickstart, compliance matrix. | High-level summary only; references detailed `docs/` files. |
| `docs/ARCHITECTURE_AND_STANDARDS.md` | Core system topology, layered architecture rules, high-level invariants, caching & pooling. | **NO raw SQL DDL or Python code**. Uses Mermaid `flowchart`, `erDiagram`, `classDiagram`, and file links. |
| `docs/SEQUENCE_DIAGRAMS.md` | Dedicated sequence diagrams covering **all** distributed execution and failure paths. | Dark-theme compatible Mermaid diagrams with step notes and recovery stages. |
| `docs/MILESTONES.md` | Project delivery roadmap (M1–M6), phase deliverables, and acceptance criteria. | Visualized with Mermaid `flowchart LR` + structured status tables. |
| `.agents/milestones/M<N>_<SLUG>.md` | Granular agent-focused procedural execution runbooks with scope fences, micro-commit sequences, and verification gates. | Direct links to SSOT architectural documents; NO duplicate code/DDL; imperative execution steps. |
| `docs/TEST_PLAN.md` | 4-tier test architecture, hybrid testcontainers configuration, and test matrix. | Visualized with Mermaid `flowchart TD` + test specification table. |
| `docs/USE_CASES.md` | Financial business scenarios, counterparty interactions, failure modes, and edge cases. | Actor-driven workflows and expected distributed invariants. |

---

## 5. Documentation Anti-Bloat & Visual Modeling Rules

Never copy-paste raw implementation code into markdown documentation files:
1. **Relational Database Schema**:
   - **Banned**: Embedding 50+ lines of raw `CREATE TABLE` DDL from `init.sql`.
   - **Mandated**: Link directly using relative paths (e.g., `[init.sql](../init.sql)`). Illustrate schema relationships, primary keys, and foreign keys using a Mermaid `erDiagram`.
2. **Pydantic Schemas & DTOs**:
   - **Banned**: Pasting 80+ lines of Pydantic model class code.
   - **Mandated**: Link directly to source files using relative paths (e.g. `[schemas.py](../app/schemas.py)`). Illustrate fields, types, and constraints using a Mermaid `classDiagram`.
3. **AMQP 0-9-1 Topology**:
   - **Banned**: Pasting Kombu Python exchange/queue definitions.
   - **Mandated**: Link directly using relative paths (e.g. `[amqp_topology.py](../shared/amqp_topology.py)`). Illustrate bindings, routing keys, and DLX routing using a Mermaid `flowchart TD`.

---

## 6. Mermaid Sequence Diagram Mandate (`docs/SEQUENCE_DIAGRAMS.md`)
All execution flows and failure paths must be documented in `docs/SEQUENCE_DIAGRAMS.md`:
- Happy Path (Zero-refresh, publisher-confirmed ingestion $\to$ Late-ack settlement)
- Worker Hard Crash (`SIGKILL`) & Redelivery Recovery (`acks_late=True`)
- The Early Ack Failure Mode (`acks_late=False`) - Proving Silent Data Loss
- Broker Hard Crash & Persistent WAL Replay / Recovery
- Poison Pill Quarantine via Dead Letter Exchange (`wire.dlx` $\to$ `wire.settlement.dlq`)

### Mermaid Render & Syntax Verification
Mermaid graphs frequently suffer from render failures due to unquoted parentheses or brackets, unescaped characters, or broken blocks. For **any** documentation additions or modifications:
1. Always quote labels containing special characters: `Node["Label (Details)"]` or `participant DB as "PostgreSQL (ACID)"`.
2. Ensure every block (`subgraph`, `rect`, `opt`, `par`, `alt`) terminates with `end`.
3. Verify renderability and syntax before proposing or committing.

---

## 7. Architecture and Standards Audit (`docs/ARCHITECTURE_AND_STANDARDS.md`)
Must audit and document:
1. Architectural Dataflow & Topology (Mermaid diagram).
2. Clean Architecture layer boundaries.
3. Standards Checklist:
   - Async API non-blocking guarantees.
   - ACID database transactions and constraint definitions.
   - Broker safety (JSON primitives only).
   - Celery canvas discipline (`chain`, `group`, `chord`, signatures).
   - Minor-unit financial precision (cents, `NUMERIC(14, 2)`).
   - Structured logging & correlation IDs (`X-Request-ID`).
   - Automated test results and 100% statement coverage table.

---

## 8. Dual-Layer Milestone & Agent Runbook Mandate

Whenever milestone documentation is generated or updated for a module (e.g. during Milestone 1 planning or milestone transitions), **always generate both documentation layers concurrently**:

### 1. Human / Lifecycle Governance Layer (`docs/MILESTONES.md`)
- Serves human developers, project leads, and auditors.
- Contains high-level roadmap (`flowchart LR`), milestone summary breakdown, acceptance criteria, and formal compliance tables.
- Keeps descriptions concise and links directly to the agent execution runbooks.

### 2. Agent Execution Runbook Layer (`.agents/milestones/M<N>_<SLUG>.md`)
- Serves autonomous AI agents executing active milestone tasks.
- Eliminates multi-hop retrieval, context bloat, and scope creep by concentrating execution contracts, constraints, and test commands in a single focused document.
- Strict rules:
  1. **Scope Fences**: Explicitly enumerate allowed in-scope files and strictly forbidden out-of-scope files.
  2. **Micro-Commit Sequence**: Detail the exact ordered sequence of single-line Conventional Commits ($\le 72$ chars) with dedicated test files, strictly honoring the one-task-per-commit rule.
  3. **SSOT Links (Anti-Bloat)**: Reference `docs/ARCHITECTURE_AND_STANDARDS.md`, `init.sql`, etc. without copying raw code.
  4. **Deterministic Verification Gates**: Provide exact shell commands for `pytest` (100% statement coverage), `mypy`, and `ruff`.

### Standard Template for `.agents/milestones/M<N>_<SLUG>.md`:
````markdown
# Milestone <N>: <Milestone Title>

> **Module**: `<module_name>`  
> **Milestone**: M<N>  
> **Status**: [Pending | In Progress | Complete]  
> **Reference SSOT**: [docs/ARCHITECTURE_AND_STANDARDS.md](../../docs/ARCHITECTURE_AND_STANDARDS.md)

## 1. Scope Boundary & Fences
* **In-Scope Files (Allowed to create / modify)**:
  - `<file_1>`
  - `<file_2>`
* **Out-of-Scope Files (Strictly forbidden to touch)**:
  - `<future_milestone_files>`

## 2. Technical Contracts & Invariants
* Domain invariant 1 (with markdown link to SSOT).
* Execution invariant 2 (e.g. `acks_late=True`, row-level locks, cents precision).

## 3. Ordered Micro-Commit Execution Sequence
Strictly follow one-task-per-commit discipline and single-line Conventional Commits (<= 72 chars):
1. `<type>(<scope>): <summary>`
   - Target files: `...`
   - Test files: `...`
2. `<type>(<scope>): <summary>`
   - Target files: `...`
   - Test files: `...`

## 4. Verification & Acceptance Gates
- Run tests: `.venv/bin/pytest <test_path> -v --cov=<module> --cov-report=term-missing`
- Statement coverage gate: 100% required.
- Type check: `.venv/bin/mypy <target>`
- Linter: `.venv/bin/ruff check <target>`
````

