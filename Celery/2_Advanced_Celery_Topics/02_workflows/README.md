# 02: Workflows

Build a document pipeline using `chain`, `group`, and `chord`.

## Deliverables

- Sequential validation and transformation tasks using `chain` and explicit signature discipline (`.s()` vs `.si()`).
- Parallel processing (fan-out) with aggregation (fan-in) using `group` and `chord`.
- A defined policy for partial failure and callback failure (e.g., `link_error` errbacks and result envelopes to avoid hung chords).
- A dedicated result backend (e.g., Redis) configured for chord synchronization with sensible `result_expires` TTL.
- Tests proving task ordering, fan-out, fan-in, and error behavior.
- JSON-safe task boundaries with no live database or request objects.

## Evidence

Include a workflow diagram and timing comparison between sequential and parallel execution.

## Project Definition: Financial Document & KYC Underwriting Pipeline

Build an asynchronous credit underwriting and compliance intelligence pipeline modeled after commercial lending and corporate spend platforms (e.g., Brex, Ramp, Blend). When an applicant company applies for a commercial credit facility, they submit a multi-document financial dossier containing:
1. **Executive Identity Verification (KYC)**: Passport/Driver's License image.
2. **Corporate Bank Statements**: Multi-page PDF statements detailing operational cash flows.
3. **Tax & Financial Filings**: Annual corporate returns / P&L statements.

Evaluating these documents sequentially creates multi-minute wait times and high customer drop-off. This service ingests the dossier, sequentially validates and unpacks the files, fans out isolated page extraction and fraud checks concurrently across Celery workers, and synchronizes via a fan-in barrier (`chord`) to compile an executive underwriting risk memo.

The central rule is:

> Multi-page financial dossiers must be validated sequentially, fanned out across parallel workers for isolated page/component extraction, and synchronized via a fan-in barrier without passing binary files or database sessions across the message broker.

## Architecture

```mermaid
flowchart TD
    Client[Client / Automated Tests] -->|POST /applications| API[FastAPI Ingestion API]
    API -->|writes metadata| DB[(PostgreSQL)]
    API -->|saves raw dossier files| Storage[Shared Document Storage]
    API -->|dispatches workflow| Broker[RabbitMQ Message Broker]

    subgraph Celery Canvas Workflow
        direction TB
        subgraph Sequential Chain: Ingestion & Preparation
            T1["1. validate_dossier (.s)<br/>• Validates Doc 1: KYC ID / Driver License (format & resolution)<br/>• Validates Doc 2: Bank Statement (PDF not encrypted)<br/>• Validates Doc 3: Tax Filing (IRS 1120 structure)"]
            T2["2. extract_and_partition_pages (.s)<br/>• Splits Bank Statement into discrete pages<br/>• Normalizes KYC Image & Tax Filing schedules<br/>• Prepares parallel task signatures"]
            T1 --> T2
        end

        subgraph Chord Header: Parallel Fan-Out across Document Types
            direction LR
            subgraph Doc1_Group ["Doc 1: Executive KYC (ID / Driver's License)"]
                P1["Worker 1: process_document_page<br/>• Parse MRZ / PDF417 barcode<br/>• Verify DOB & Expiration Date<br/>• Cross-check applicant name"]
            end
            subgraph Doc2_Group ["Doc 2: Corporate Bank Statement (Cashflows)"]
                P2["Worker 2: process_document_page (Page 1)<br/>• OCR transaction table<br/>• Inflows & opening balance"]
                P3["Worker 3: process_document_page (Page 2)<br/>• OCR transaction table<br/>• Outflows & debt service"]
            end
            subgraph Doc3_Group ["Doc 3: Tax & Financial Filings (IRS 1120 / P&L)"]
                P4["Worker 4: process_document_page<br/>• Extract annual revenue & EBITDA<br/>• Calculate baseline DTI ratio"]
            end
            T2 --> Doc1_Group
            T2 --> Doc2_Group
            T2 --> Doc3_Group
        end

        subgraph Chord Barrier & Synchronization
            P1 --> RedisBarrier[(Redis Result Backend)]
            P2 --> RedisBarrier
            P3 --> RedisBarrier
            P4 --> RedisBarrier
        end

        subgraph Chord Callback: Fan-In Aggregation
            RedisBarrier -->|atomic barrier reaches 0| Callback["compile_underwriting_decision (.s)<br/>• Validates KYC clearance (Doc 1)<br/>• Aggregates Net Cashflow & AMB (Doc 2)<br/>• Reconciles DSCR against Revenue (Doc 3)<br/>• Generates Executive Underwriting Memo"]
        end

        subgraph Error Handling
            T1 -.->|link_error| Errback["handle_pipeline_failure (.si)<br/>• Catches missing mandatory KYC or corrupt PDFs<br/>• Marks status: failed & logs audit root cause"]
            T2 -.->|link_error| Errback
            Callback -.->|link_error| Errback
        end
    end

    Broker --> T1
    Callback -->|reads/writes| DB
    Callback -->|generates summary memo| Storage
    Errback -->|marks failed & logs cause| DB
```

### Responsibilities

| Component | Responsibility |
| --- | --- |
| **FastAPI** | Validates incoming application requests, stores uploaded raw documents in shared storage, persists the initial application record in PostgreSQL, initiates the Celery Canvas workflow, and returns `202 Accepted` with an application ID. |
| **PostgreSQL** | Stores applications, document metadata, page components, extraction line items, and the final underwriting decision memo. Never stores raw file blobs. |
| **Shared Storage** | Local volume or filesystem mount storing raw PDF/image files and extracted text/redacted artifacts. Celery tasks pass only storage paths and UUIDs. |
| **RabbitMQ** | High-performance message broker delivering Celery task messages and routing workflow queues. |
| **Redis** | Dedicated Celery `result_backend` responsible for atomic countdown barriers in `chord` fan-in, temporary task state storage, and result collection with automatic TTL expiration. |
| **Celery Workers** | Execute the Canvas stages: sequential validation (`chain`), concurrent page/component analysis (`group`), and final metric synthesis (`chord` callback). |

### Task Descriptions & Workflow Stages

| Task Name | Canvas Stage | Signature | Detailed Responsibility |
| --- | --- | --- | --- |
| **`workflow.validate_dossier`** | Sequential Chain (Gatekeeper) | `validate_dossier.s(application_id)` | **Lightweight Manifest & File Check:**<br/>1. Verifies physical file existence on shared storage and checks SHA-256 integrity hashes.<br/>2. Inspects magic bytes (PNG/JPEG for KYC, `%PDF-1.x` for Bank Statement & Tax Filing).<br/>3. Verifies non-encryption (PDFs are not password-locked).<br/>4. Asserts presence of mandatory files (KYC + Bank Statement).<br/>5. Updates DB application status to `validating`. |
| **`workflow.extract_and_partition_pages`** | Sequential Chain (Preparation) | `extract_and_partition_pages.s(validation_result)` | **Document Unpacking & Signature Generation:**<br/>1. Splits multi-page Bank Statement PDF into individual single-page files (`page_1.pdf`, `page_2.pdf`).<br/>2. Registers each page/component row in `document_pages` with status `pending`.<br/>3. Dynamically constructs the Celery `chord` header: creates a `process_document_page.s(page_id)` task for each page across all document types.<br/>4. Returns the chord signature to be executed. |
| **`workflow.process_document_page`** | Chord Header (Parallel Fan-Out) | `process_document_page.s(page_id)` | **Heavy Concurrent Analysis (Specialized by Document Type):**<br/>• **Doc 1 (KYC ID / License):** Extracts MRZ / PDF417 barcode, verifies expiration date > today, checks applicant age $\ge 18$, and verifies name match.<br/>• **Doc 2 (Bank Statement Pages):** Performs OCR on transaction tables, classifies inflow credits vs outflow debits, calculates net page balance change.<br/>• **Doc 3 (Tax Filing Schedules):** Extracts annual revenue, EBITDA, and debt liabilities.<br/>• **Common:** Runs regex PII masking and wraps output in a Result Envelope (`status: 'ok' \| 'degraded'`). |
| **`workflow.compile_underwriting_decision`** | Chord Callback (Fan-In Barrier) | `compile_underwriting_decision.s(page_results, application_id)` | **Multi-Document Synthesis & Underwriting Memo:**<br/>1. Awaits atomic Redis countdown barrier completion across all parallel page tasks.<br/>2. Validates that Executive KYC passed cleanly.<br/>3. Sums total credits/debits across bank statement pages to calculate Average Monthly Balance (AMB) and Net Cashflow.<br/>4. Reconciles Debt Service Coverage Ratio (DSCR) against Tax Return revenue.<br/>5. Inspects for degraded envelopes: if non-critical page degraded $\to$ flags `manual_review`; if clean & risk score $\ge 70 \to$ flags `approved`.<br/>6. Inserts `underwriting_memos` record and updates application to final terminal status. |
| **`workflow.handle_pipeline_failure`** | Error Errback (`link_error`) | `handle_pipeline_failure.si(application_id)` | **Compensating Action & Failure Recovery:**<br/>1. Attached via `.on_error()` on the canvas workflow.<br/>2. If `validate_dossier` or `extract_and_partition_pages` raises an unhandled exception (e.g. missing mandatory KYC or corrupt PDF), Celery routes execution here.<br/>3. Updates `applications` status to `failed`, logs root cause exception in `last_error`, and unblocks caller without orphaned worker jobs. |

### Architectural Decision: Single Gatekeeper Task vs. Parallel Validation

> [!NOTE]
> **Why is `validate_dossier` a single sequential task instead of 3 parallel tasks?**
>
> 1. **Task Granularity & Broker Overhead:**
>    In distributed task systems, publishing a task message to RabbitMQ carries non-zero latency (~5–10 ms for message serialization, network hops, queue acknowledgment, and worker process context switching). Checking file headers and magic bytes takes **< 5 milliseconds total** for all 3 files. Fanning out 3 separate Celery tasks for microsecond checks would spend $90\%$ of the time on broker communication rather than useful CPU work.
>
> 2. **Atomic Manifest Consistency (The Multi-Document Rule):**
>    Underwriting rules require an atomic question: *"Does this application contain BOTH a valid KYC ID AND a Bank Statement?"* A single gatekeeper inspects the combined manifest as a single atomic unit. If validation were split across 3 parallel tasks, Celery would require an extra intermediate `chord` barrier just to assemble the validation verdict before beginning the actual extraction.
>
> 3. **Where Concurrency Yields True ROI:**
>    Concurrency is intentionally reserved for the **heavy, high-latency stage** (`process_document_page`): OCR table extraction, image decoding, regex PII masking, and checksum verification. This is where parallelizing across workers reduces wall-clock execution from 45 seconds down to 6 seconds.

### Project Structure

```text
02_workflows/
├── README.md                   # Project definition, architecture, workflows, and deliverables
├── .env.example                # Environment variables (Postgres, RabbitMQ, Redis)
├── .gitignore                  # Git ignore rules for virtualenv, temporary files, and uploads
├── Dockerfile.api              # FastAPI container definition
├── Dockerfile.worker           # Celery worker container definition
├── Dockerfile.postgres         # Custom PostgreSQL image with initial schemas
├── docker-compose.yml          # Multi-container orchestration (API, Worker, Postgres, RabbitMQ, Redis)
├── init.sql                    # Database DDL (applications, documents, pages, underwriting_memos)
├── pytest.ini                  # Pytest configuration
├── requirements.txt            # Core runtime dependencies (FastAPI, Celery, Redis, SQLAlchemy, Psycopg)
├── requirements-api.txt        # API-specific dependencies
├── requirements_dev.txt        # Development & test dependencies
├── app/                        # FastAPI Ingestion & Query Service
│   ├── __init__.py
│   ├── config.py               # Pydantic environment settings
│   ├── db.py                   # Async database engine & sessionmaker
│   ├── logging_config.py       # JSON structured logging
│   ├── main.py                 # Application factory & lifespan
│   ├── models.py               # SQLAlchemy ORM models
│   ├── routes.py               # API endpoints (/applications, /dossier, /timing)
│   ├── schemas.py              # Pydantic request & response models
│   └── tasks.py                # Celery client dispatching canvas workflows
├── services/
│   └── worker/                 # Celery Worker Service
│       ├── Dockerfile          # Worker image
│       ├── celery_app.py       # Celery configuration (RabbitMQ broker + Redis result_backend)
│       ├── tasks.py            # Canvas tasks (validate_dossier, extract_and_partition, process_page, etc.)
│       └── processors/         # Document domain processors
│           ├── __init__.py
│           ├── kyc_processor.py         # MRZ & identity verification
│           ├── statement_processor.py   # Bank statement transaction ledger parsing
│           └── tax_processor.py         # IRS Form 1120 / P&L parser
├── scripts/
│   ├── generate_fixtures.py    # Generates synthetic test PDF/JPG dossiers
│   └── benchmark.py            # Automated sequential vs parallel timing harness
├── requests/
│   └── requests.rest           # REST Client requests for manual API inspection
└── tests/
    ├── __init__.py
    ├── conftest.py             # Test fixtures & database containers
    ├── test_api.py             # API endpoint tests
    ├── test_canvas_workflows.py # Tests for chain, group, chord, link_error
    ├── test_partial_failure.py # Tests for degraded Result Envelope
    └── fixtures/               # Test datasets & assets
        ├── assets/
        │   └── kyc_specimen_jane_doe.jpg # High-resolution photographic specimen template
        ├── clean_4pages/       # Happy path: KYC ID + 4-page Bank Statement + Tax Filing
        ├── benchmark_16pages/  # Concurrency benchmark: 16-page Bank Statement
        ├── degraded_page2/     # Partial failure: Statement with unreadable Page 2
        └── corrupted/          # Fatal error: Corrupted binary to test link_error
```

---

## Mapping to Deliverables

| Deliverable | Implementation in Pipeline |
| --- | --- |
| **Sequential Tasks (`chain`)** | `validate_dossier` $\to$ `extract_and_partition_pages`. The splitter task requires the validated metadata and checksums of the first task before it can safely partition pages. |
| **Signature Discipline (`.s()` vs `.si()`)** | Mutable `.s()` is used when the extracted page list flows from `extract_and_partition_pages` into the chord header. Immutable `.si()` is used for independent notifications or `link_error` cleanup callbacks that do not accept injected prior results. |
| **Parallel Fan-out (`group`)** | Multi-page bank statements and KYC documents are split into discrete page items. Each page is dispatched as an independent task in a `group`, allowing multiple workers to perform OCR simulation, PII masking, and cashflow extraction concurrently. |
| **Fan-in Aggregation (`chord`)** | The `chord` header tracks all page tasks. Once the last page completes, Celery atomically invokes `compile_underwriting_decision`, passing the aggregated array of page results into the callback. |
| **Partial Failure Policy** | Individual page tasks use **Result Envelopes** (`{"page_id": ..., "status": "ok"|"degraded", "metrics": ...}`). If a supplementary statement page fails OCR, the envelope records a warning and the chord completes with `manual_review` status instead of deadlocking. |
| **Callback & Workflow Error Policy** | Unrecoverable exceptions (e.g., corrupt PDF, storage IO failure) trigger an attached `link_error` errback (`handle_pipeline_failure.si(application_id)`), transitioning the application status to `failed` and unlocking resources. |
| **Dedicated Result Backend (Redis)** | Redis is configured as `result_backend` for chord state management, with `result_expires = 3600` to prevent memory leaks from completed or orphaned chord headers. |
| **JSON-Safe Boundaries** | Task arguments and return values contain strictly JSON-serializable primitives: UUID strings, integers, floats, and storage relative paths. No database ORM models or file streams cross broker boundaries. |
| **Timing Evidence** | A benchmark harness compares pure sequential execution vs. parallel chord execution across varying worker pool concurrency ($C=1, 2, 4, 8$). |

---

## Services & Tasks

### 1. Ingestion API (FastAPI)

Endpoints:
```text
POST /applications
GET  /applications/{application_id}
GET  /applications/{application_id}/dossier
GET  /applications/{application_id}/timing
```

Responsibilities:
- Validate `Idempotency-Key` header, applicant metadata, and uploaded document types (PDF/PNG).
- Save uploaded files to the shared storage volume under `uploads/{application_id}/`.
- Create a local record in `applications` with initial status `pending`.
- Dispatch the Celery workflow: `build_underwriting_workflow(application_id).apply_async()`.
- Return `202 Accepted` with the application ID and tracking URLs.

### 2. Celery Worker Tasks

| Task Name | Stage | Input Signature | Output Envelope |
| --- | --- | --- | --- |
| `workflow.validate_dossier` | Chain (Step 1) | `application_id: str` | `{"application_id": str, "documents": list[dict], "valid": bool}` |
| `workflow.extract_and_partition_pages` | Chain (Step 2) | `validation_result: dict` | `{"application_id": str, "page_ids": list[str]}` |
| `workflow.process_document_page` | Chord Header (Fan-Out) | `page_id: str` | `{"page_id": str, "status": "ok"\|"degraded", "cashflow_inflow": int, "cashflow_outflow": int, "pii_redacted": int, "error": str\|None}` |
| `workflow.compile_underwriting_decision` | Chord Callback (Fan-In) | `page_results: list[dict], application_id: str` | `{"application_id": str, "decision": str, "dscr": float, "amb": int, "risk_score": int, "status": str}` |
| `workflow.handle_pipeline_failure` | Error Errback (`link_error`) | `application_id: str` (via `.si()`) | `{"application_id": str, "status": "failed", "error": str}` |

---

## Data Models

```mermaid
erDiagram
    APPLICATIONS ||--o{ DOCUMENTS : contains
    DOCUMENTS ||--o{ DOCUMENT_PAGES : has
    APPLICATIONS ||--o| UNDERWRITING_MEMOS : produces
```

### Applications Table
```text
applications
------------
id                  UUID primary key
company_name        VARCHAR not null
requested_amount    BIGINT not null
currency            CHAR(3) not null default 'USD'
status              VARCHAR not null default 'pending'
decision            VARCHAR nullable
risk_score          INTEGER nullable
created_at          TIMESTAMP not null default now()
updated_at          TIMESTAMP not null default now()
```

### Documents Table
```text
documents
---------
id                  UUID primary key
application_id      UUID foreign key -> applications.id
document_type       VARCHAR not null  -- 'bank_statement', 'tax_return', 'kyc_id'
file_path           VARCHAR not null
file_hash           VARCHAR not null
page_count          INTEGER not null default 0
status              VARCHAR not null default 'pending'
created_at          TIMESTAMP not null default now()
```

### Document Pages Table
```text
document_pages
--------------
id                  UUID primary key
document_id         UUID foreign key -> documents.id
page_number         INTEGER not null
file_path           VARCHAR not null
status              VARCHAR not null default 'pending' -- 'pending', 'processed', 'degraded', 'failed'
inflow_minor_units  BIGINT not null default 0
outflow_minor_units BIGINT not null default 0
pii_detected_count  INTEGER not null default 0
error_message       TEXT nullable
processed_at        TIMESTAMP nullable
```

### Underwriting Memos Table
```text
underwriting_memos
------------------
id                  UUID primary key
application_id      UUID unique foreign key -> applications.id
total_inflow        BIGINT not null
total_outflow       BIGINT not null
net_cash_flow       BIGINT not null
avg_monthly_balance BIGINT not null
dscr_ratio          NUMERIC(5,2) not null
recommendation      VARCHAR not null  -- 'approved', 'manual_review', 'rejected'
degraded_pages_count INTEGER not null default 0
summary_notes       TEXT not null
generated_at        TIMESTAMP not null default now()
```

### State Machine

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> validating: API triggers chain
    validating --> partitioning: validate_dossier passes
    partitioning --> processing_pages: extract_and_partition_pages fans out
    processing_pages --> aggregating: all chord header tasks complete
    aggregating --> approved: all checks clean & risk acceptable
    aggregating --> manual_review: degraded pages or borderline DTI
    aggregating --> rejected: high fraud markers or cash flow deficit
    validating --> failed: validation error / link_error
    partitioning --> failed: partition error / link_error
    processing_pages --> failed: fatal unhandled error / link_error
```

---

## Failure Policy & Edge Cases

### 1. Partial Failure in Header (Degraded Mode)
* **Problem:** If a Celery task in a chord header raises an unhandled exception, Celery marks that task `FAILURE` and discards the chord callback. The entire workflow stays permanently incomplete.
* **Policy:** Page tasks must catch non-fatal processing errors (e.g. low OCR confidence, non-standard layout, partial scan tear) and return a **Result Envelope**:
  ```python
  return {
      "page_id": page_id,
      "status": "degraded",
      "cashflow_inflow": 0,
      "cashflow_outflow": 0,
      "pii_redacted": 0,
      "error": "OCR low confidence (< 60%)"
  }
  ```
* The Redis chord barrier decrements normally. When `compile_underwriting_decision` runs, it inspects all envelopes: if any page is `degraded`, it records an audit flag and downgrades the application recommendation to `manual_review`.

### 2. Fatal Pipeline Failure (`link_error` Errback)
* **Problem:** If a file is completely corrupted, missing from storage, or a worker suffers an Out-Of-Memory kill during validation/partitioning, the application should not hang in `validating` forever.
* **Policy:** Attach `handle_pipeline_failure.si(application_id)` as `link_error` on the canvas signatures:
  ```python
  workflow = (
      chain(
          validate_dossier.s(application_id),
          extract_and_partition_pages.s(),
          build_chord_barrier.s()
      )
  ).on_error(handle_pipeline_failure.si(application_id))
  ```
* The errback runs with an immutable signature (`.si()`), updates PostgreSQL status to `failed`, records the error traceback in `applications.last_error`, and emits an alert.

### 3. Redis Result Expiration (TTL)
* `result_expires = 3600` is enforced on the Celery configuration.
* Intermediate task results in Redis expire after 1 hour, preventing memory leakage while ensuring sufficient time for long chords to complete.

---

## Sequence Diagrams

### Use Case 1: Normal Processing (Sequential Chain $\to$ Parallel Fan-Out Chord $\to$ Fan-In Callback)

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI
    participant DB as PostgreSQL
    participant FS as Shared Storage
    participant B as RabbitMQ Broker
    participant W as Celery Worker
    participant R as Redis Result Backend

    C->>API: POST /applications (dossier upload)
    API->>FS: Write raw documents to uploads
    API->>DB: Insert application (status: pending)
    API->>B: Dispatch Canvas Workflow (validate_dossier)
    API-->>C: 202 Accepted (application_id)

    Note over B,W: Stage 1: Sequential Chain (Gatekeeper)
    B->>W: Deliver validate_dossier(app_id)
    W->>FS: Verify files (KYC PNG, Bank Stmt PDF, Tax Return PDF)
    W->>DB: Update application (status: validating)
    W->>B: Trigger extract_and_partition_pages(validation_result)

    B->>W: Deliver extract_and_partition_pages
    W->>FS: Split Bank Statement into pages
    W->>DB: Insert document_pages rows (status: pending)
    W->>B: Dispatch Chord (Header: 4 tasks, Callback: compile_underwriting_decision)

    Note over W,R: Stage 2: Parallel Fan-Out (Chord Header across Document Types)
    par Doc 1: KYC ID / Driver License
        W->>W: Worker 1: verify MRZ, barcode, and active expiration
        W->>R: Save result_kyc (status: ok, kyc_cleared: true)
    and Doc 2: Bank Statement Page 1
        W->>W: Worker 2: OCR transaction table (Credits: +18000)
        W->>R: Save result_bank_p1 (status: ok, inflow: 18000)
    and Doc 2: Bank Statement Page 2
        W->>W: Worker 3: OCR transaction table (Debits: -9000)
        W->>R: Save result_bank_p2 (status: ok, outflow: 9000)
    and Doc 3: Tax Filing IRS 1120
        W->>W: Worker 4: extract annual revenue 250k, EBITDA 45k
        W->>R: Save result_tax (status: ok, ebitda: 45000)
    end

    Note over R,W: Stage 3: Fan-In Barrier & Multi-Document Aggregation
    R->>R: Atomic barrier count decrements to 0
    R->>B: Enqueue compile_underwriting_decision
    B->>W: Deliver compile_underwriting_decision
    W->>DB: Synthesize docs: KYC verified, Net Cashflow +9000, DSCR 3.33
    W->>DB: Insert underwriting_memo (decision: approved)
    W->>DB: Update application (status: approved, risk_score: 88)
    W-->>B: Acknowledge message

    C->>API: GET /applications/id/dossier
    API->>DB: Read underwriting_memo and status
    DB-->>API: Status: approved
    API-->>C: 200 OK (Underwriting memo returned)
```

### Use Case 2: Partial Failure (Degraded Page Recovery)

```mermaid
sequenceDiagram
    autonumber
    participant B as RabbitMQ
    participant W as Celery Worker
    participant R as Redis Result Backend
    participant DB as PostgreSQL

    Note over B,W: Stage 2: Parallel Fan-Out (Chord Header with 1 Degraded Task)
    par Doc 1: KYC ID / Driver License
        W->>W: Worker 1: verify MRZ, barcode, active expiration
        W->>R: Save result_kyc (status: ok, kyc_cleared: true)
    and Doc 2: Bank Statement Page 1
        W->>W: Worker 2: OCR transaction table (Credits: +18000)
        W->>R: Save result_bank_p1 (status: ok, inflow: 18000)
    and Doc 2: Bank Statement Page 2 (Degraded Scan)
        W->>W: Worker 3: OCR fails due to low image contrast
        W->>DB: Update document_pages (status: degraded, error: Low OCR quality)
        W->>R: Save result_bank_p2 Result Envelope (status: degraded)
    and Doc 3: Tax Filing IRS 1120
        W->>W: Worker 4: extract annual revenue 250k, EBITDA 45k
        W->>R: Save result_tax (status: ok, ebitda: 45000)
    end

    Note over R,W: Stage 3: Fan-In Barrier & Degraded Recovery
    R->>R: Atomic barrier count decrements to 0
    Note over R: All 4 envelopes gathered in Redis (3 ok, 1 degraded)
    R->>B: Enqueue compile_underwriting_decision
    B->>W: Deliver compile_underwriting_decision
    W->>W: Evaluates results: detects degraded Bank Stmt Page 2
    W->>DB: Insert underwriting_memo (decision: manual_review, warning: Page 2 unreadable)
    W->>DB: Update application (status: manual_review)
```

### Use Case 3: Fatal Error & `link_error` Compensation

```mermaid
sequenceDiagram
    autonumber
    participant B as RabbitMQ
    participant W as Celery Worker
    participant DB as PostgreSQL

    Note over B,W: Stage 1: Sequential Chain (Fatal Gatekeeper Error)
    B->>W: Deliver validate_dossier(app_id)
    W->>W: Mandatory Doc 1 (KYC ID / Driver License) is missing or corrupt
    W->>W: Raise MandatoryDocumentMissingError
    Note over W,B: Celery catches unhandled exception and halts sequential chain
    B->>W: Route to link_error errback: handle_pipeline_failure(app_id)
    W->>DB: Update application (status: failed, last_error: Missing required KYC ID)
    W->>DB: Record failure timestamp and audit log
    W-->>B: Acknowledge errback execution
```

---

## Benchmarking & Concurrency Evidence

To satisfy the **Evidence** deliverable, the repository includes an automated timing harness comparing:
1. **Pure Sequential Execution**: Running all pre-processing and page tasks sequentially in a single `chain`.
2. **Parallel Chord Execution**: Running page extraction across a concurrent Celery worker pool ($C=4$ or $C=8$).

### Theoretical Speedup
For a dossier with $P$ pages where average page processing time is $t_{\text{page}}$, validation is $t_{\text{val}}$, and aggregation is $t_{\text{agg}}$:
$$\text{Latency}_{\text{sequential}} = t_{\text{val}} + \sum_{i=1}^P t_{\text{page}_i} + t_{\text{agg}}$$
$$\text{Latency}_{\text{parallel}} \approx t_{\text{val}} + \left\lceil \frac{P}{C} \right\rceil \cdot t_{\text{page}} + t_{\text{chord\_barrier}} + t_{\text{agg}}$$

### Benchmark Output Format
The harness records execution logs and produces:
* A markdown timing table comparing wall-clock duration across 4, 8, and 16-page dossiers.
* Speedup ratio calculation ($\text{Speedup} = T_{\text{seq}} / T_{\text{par}}$).
* Worker pool utilization and Redis barrier overhead measurements.

---

## Completion Checklist

- [ ] FastAPI creates applications, stores files in shared storage, and returns `202 Accepted`.
- [ ] Celery messages pass only JSON-safe UUIDs and storage keys; no raw files or ORM models.
- [ ] Sequential pre-processing (`chain`) correctly enforces task ordering (`validate` $\to$ `partition`).
- [ ] Task argument isolation is maintained using `.s()` for piped inputs and `.si()` for fixed calls.
- [ ] Parallel fan-out (`group`) processes pages concurrently across multiple worker processes.
- [ ] Redis result backend coordinates the fan-in barrier (`chord`) and triggers the decision callback.
- [ ] Result envelope pattern allows graceful partial degradation when non-critical pages fail.
- [ ] `link_error` errback reliably captures fatal exceptions, updates DB status, and prevents zombie tasks.
- [ ] Unit and integration tests verify ordering, fan-out, barrier synchronization, and error handling.
- [ ] Benchmark test generates timing comparison demonstrating parallel vs. sequential speedup.
- [ ] Docker Compose stack runs FastAPI, PostgreSQL, RabbitMQ, Redis, and Celery Workers with health checks.
