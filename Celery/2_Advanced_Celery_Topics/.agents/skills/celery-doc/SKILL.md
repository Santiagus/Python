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

## 4. Mermaid Sequence Diagram Mandate (All Execution Paths)
Architecture documentation must include a comprehensive `sequenceDiagram` mapping out **every path through the system**:

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as FastAPI Router
    participant DB as PostgreSQL (ACID)
    participant Broker as RabbitMQ Broker
    participant W_Val as Worker (Validation)
    participant W_Fan as Workers (Parallel Fan-Out)
    participant Redis as Redis Backend
    participant W_Agg as Worker (Callback Aggregator)

    %% PATH 1: Happy Path
    rect rgb(235, 245, 235)
        Note over Client,W_Agg: Path 1: Happy Path Workflow
        Client->>API: POST /resource (Payload)
        API->>DB: INSERT initial record (status='pending')
        API->>Broker: Dispatch validate_task.s() with link_error
        API-->>Client: 202 Accepted {id, status: 'pending'}
        Broker->>W_Val: Consume validation task
        W_Val->>DB: Update status='validating'
        W_Val->>Broker: Dispatch Chord (Header Tasks -> Callback)
        par Parallel Execution
            Broker->>W_Fan: Header Task 1
            Broker->>W_Fan: Header Task 2
        end
        W_Fan->>Redis: Store partial results & decrement barrier
        Redis->>Broker: Barrier reached -> Trigger Callback
        Broker->>W_Agg: Consume aggregate_task()
        W_Agg->>DB: UPDATE status='completed', persist decision memo
    end

    %% PATH 2: Degraded / Partial Failure Path
    rect rgb(255, 250, 235)
        Note over W_Fan,DB: Path 2: Partial Degradation (Result Envelope)
        W_Fan-->>Redis: Return ResultEnvelope(status='degraded', warnings=['Low confidence'])
        Redis->>Broker: Barrier reached -> Trigger Callback
        Broker->>W_Agg: Consume aggregate_task()
        W_Agg->>DB: UPDATE status='manual_review' (non-fatal routing)
    end

    %% PATH 3: Fatal Error & Errback Compensation
    rect rgb(255, 235, 235)
        Note over W_Val,DB: Path 3: Fatal Error & link_error Errback
        W_Val->>W_Val: Fatal error / Corrupt payload detected
        W_Val->>Broker: Dispatch link_error (handle_failure.s)
        Broker->>W_Val: Consume handle_failure
        W_Val->>DB: UPDATE status='failed', record error traceback
    end
```

---

## 5. Architecture and Standards Audit (`docs/ARCHITECTURE_AND_STANDARDS.md`)
Must audit and document:
1. Architectural Dataflow & Topology (Mermaid diagram).
2. Standards Checklist:
   - Async API non-blocking guarantees.
   - ACID database transactions and constraint definitions.
   - Broker safety (JSON primitives only).
   - Celery canvas discipline (`chain`, `group`, `chord`, signatures).
   - Minor-unit financial precision (cents, `NUMERIC(14, 2)`).
   - Structured logging & correlation IDs (`X-Request-ID`).
   - Automated test results and 100% statement coverage table.

