# Architecture, Observability Telemetry & Operations Specification

> **Module**: `06_observability_and_operations`  
> **System**: Real-Time Fraud Detection & AML Sanctions Screening Rail  
> **Standard Compliance**: Production-Grade Distributed Celery, Prometheus, OpenTelemetry, Kombu AMQP 0-9-1, FastAPI Async, PostgreSQL ACID

---

## 1. System Architecture & Topology

The system orchestrates real-time fraud scoring and sanctions compliance screening across decoupled microservices. Real-time velocity and scoring tasks execute on high-priority queues, while deep AML sanctions queries route to secondary workers or partner APIs with circuit breakers.

```mermaid
flowchart TD
    Client["Client / Payment Rail"] -->|HTTP POST /screenings| IngestionAPI["FastAPI Ingestion Gateway<br/>(Producer)"]
    
    subgraph StorageLayer["ACID Storage & Coordination"]
        DB[("PostgreSQL 16<br/>(Screenings Ledger)")]
        RedisState[("Redis 7 Cache<br/>(Velocity & Idempotency)")]
    end

    subgraph MessagingBroker["RabbitMQ 3.13 AMQP Broker"]
        ExDirect["Direct Exchange: fraud.direct"]
        ExDLX["DLX Exchange: fraud.dlx"]
        QScreening["Queue: fraud.screening.critical"]
        QAML["Queue: fraud.aml.bulk"]
        QDLQ["Queue: fraud.screening.dlq"]
    end

    subgraph WorkerFleet["Distributed Celery Workers"]
        WFast["Worker: worker_fraud_screening<br/>(Concurrency: 4, Prefetch: 1)"]
        WAML["Worker: worker_aml_watchlist<br/>(Concurrency: 2, Prefetch: 2)"]
    end

    subgraph ExternalPartner["Standalone Partner APIs"]
        SanctionsAPI["Sanctions Watchlist Simulator API<br/>(:8015/api/v1/watchlists/check)"]
    end

    subgraph TelemetryStack["Observability & Operations Console"]
        Prometheus["Prometheus Server<br/>(:9090 Scraping /metrics)"]
        Loki["Grafana Loki Engine<br/>(:3100 Log Ingestion)"]
        Promtail["Promtail Log Collector<br/>(Docker JSON Streamer)"]
        GrafanaDash["Grafana Dashboard<br/>(:3000 Unified Metrics & Logs)"]
        FlowerDash["Celery Flower Console<br/>(:5555 Process Introspection)"]
    end

    IngestionAPI -->|1. Immediate In-Flight Insert| DB
    IngestionAPI -->|2. Fast-Path Velocity Check| RedisState
    IngestionAPI -->|3. Publish AMQP Task| ExDirect
    ExDirect -->|fraud.screening.critical| QScreening
    ExDirect -->|fraud.aml.bulk| QAML
    QScreening -->|Consume Real-Time Task| WFast
    QAML -->|Consume AML Watchlist Task| WAML
    WFast -->|Audit Updates & Risk Score| DB
    WAML -->|Query External OFAC/PEP| SanctionsAPI
    WAML -->|Persist Watchlist Hits| DB
    
    QScreening -.->|Dead Letter on Fatal Error| ExDLX
    ExDLX --> QDLQ

    IngestionAPI -->|Metrics Scraping| Prometheus
    WFast -->|Metrics Scraping| Prometheus
    MessagingBroker -.->|Broker Inspection| FlowerDash
    WorkerFleet -.->|Events & Heartbeats| FlowerDash
    IngestionAPI -->|JSON stdout| Promtail
    WFast -->|JSON stdout| Promtail
    WAML -->|JSON stdout| Promtail
    Promtail -->|Push Log Streams| Loki
    Prometheus -->|Metrics Datasource| GrafanaDash
    Loki -->|Logs Datasource| GrafanaDash
```

---

## 2. Data Models & Schema Design

### 2.1 Database Tables (`init.sql`)

```sql
-- 1. Master Screenings Table (ACID Financial Ledger)
CREATE TABLE IF NOT EXISTS screenings (
    id UUID PRIMARY KEY,
    transaction_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    client_ip VARCHAR(45) NOT NULL,
    risk_score INT DEFAULT NULL CHECK (risk_score >= 0 AND risk_score <= 100),
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    decision_reason VARCHAR(255) DEFAULT NULL,
    latency_ms NUMERIC(8, 2) DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_screenings_tx UNIQUE (transaction_id),
    CONSTRAINT ck_screening_status CHECK (
        status IN ('pending', 'processing', 'approved', 'flagged_review', 'blocked', 'failed')
    )
);

-- 2. Partial B-Tree Index for In-Flight State Visibility
-- Eliminates write amplification on terminal states; keeps active records in CPU L3 cache
CREATE INDEX IF NOT EXISTS idx_screenings_active_status 
ON screenings (created_at DESC) 
WHERE status IN ('pending', 'processing');

-- 3. Watchlist Hits Table (Compliance Sanctions Audit)
CREATE TABLE IF NOT EXISTS watchlist_hits (
    id UUID PRIMARY KEY,
    screening_id UUID NOT NULL REFERENCES screenings(id) ON DELETE CASCADE,
    entity_name VARCHAR(255) NOT NULL,
    watchlist_type VARCHAR(32) NOT NULL, -- 'OFAC_SDN', 'EU_SANCTIONS', 'PEP'
    match_confidence NUMERIC(5, 2) NOT NULL, -- e.g. 98.50
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watchlist_hits_screening_id 
ON watchlist_hits (screening_id);

-- 4. Operational Audit Log (Diagnostic Event Store)
CREATE TABLE IF NOT EXISTS operational_events (
    id UUID PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64) DEFAULT NULL,
    event_type VARCHAR(64) NOT NULL, -- 'QUEUE_AGE_BREACH', 'EXTERNAL_TIMEOUT', 'CIRCUIT_BREAKER_OPEN'
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operational_events_correlation 
ON operational_events (correlation_id);
```

### 2.2 Invariant Guarantees
1. **Index Deduplication**: No redundant index on `transaction_id` or `id` (automatically indexed by `PRIMARY KEY` and `UNIQUE` constraints).
2. **Minor-Unit Financial Arithmetic**: Financial values processed internally as integer cents (`amount_cents BIGINT`) and formatted as `NUMERIC(14, 2)` across API boundaries.
3. **In-Flight State Visibility**: On `POST /api/v1/screenings`, an initial row with `status="processing"` is committed to PostgreSQL **before** returning `HTTP 202 ACCEPTED`. Immediate `GET /api/v1/screenings/{id}` calls return `HTTP 200 OK` with `status="processing"`, eliminating observable black holes.

---

## 3. Distributed Sequence Diagrams (All Execution Paths)

### Path 1: Happy Path Real-Time Screening (Low Risk, Auto-Approved)
```mermaid
sequenceDiagram
    autonumber
    actor Client as "Client Application"
    participant API as "FastAPI Gateway"
    participant DB as "PostgreSQL (ACID)"
    participant Broker as "RabbitMQ (AMQP)"
    participant W_Fast as "Worker (Scoring)"
    participant W_AML as "Worker (AML)"
    participant Sanctions as "Sanctions API"

    Note over Client,Sanctions: Path 1: Happy Path Real-Time Screening (P99 <= 120ms)
    Client->>API: POST /api/v1/screenings (Payload, X-Request-ID)
    API->>DB: INSERT screening (status='processing')
    API->>Broker: Publish evaluate_screening.s() with W3C traceparent
    API-->>Client: HTTP 202 Accepted {id, status: 'processing'}
    
    Broker->>W_Fast: Consume fraud.screening.critical
    W_Fast->>W_Fast: Compute velocity & IP reputation (Score: 12)
    W_Fast->>Broker: Dispatch check_aml_watchlist.s(id)
    
    Broker->>W_AML: Consume fraud.aml.bulk
    W_AML->>Sanctions: POST /watchlists/check (Entity Name)
    Sanctions-->>W_AML: HTTP 200 {matches: []}
    W_AML->>DB: UPDATE status='approved', risk_score=12
    W_AML->>W_AML: Record Prometheus duration metric
```

### Path 2: High-Risk AML Watchlist Match (Flagged for Review)
```mermaid
sequenceDiagram
    autonumber
    actor Client as "Client Application"
    participant API as "FastAPI Gateway"
    participant DB as "PostgreSQL (ACID)"
    participant Broker as "RabbitMQ (AMQP)"
    participant W_AML as "Worker (AML)"
    participant Sanctions as "Sanctions API"

    Note over Client,Sanctions: Path 2: AML Watchlist Match & Compliance Flagging
    Broker->>W_AML: Consume fraud.aml.bulk
    W_AML->>Sanctions: POST /watchlists/check (Entity Name)
    Sanctions-->>W_AML: HTTP 200 {matches: [{entity: 'KNOWN ALIAS', confidence: 99.2}]}
    W_AML->>DB: INSERT watchlist_hits (screening_id, match details)
    W_AML->>DB: UPDATE status='flagged_review', risk_score=95
    W_AML->>W_AML: Increment metric celery_tasks_aml_flagged_total
```

### Path 3: External Watchlist Degradation & Circuit-Breaker Fallback (Result Envelope)
```mermaid
sequenceDiagram
    autonumber
    participant Broker as "RabbitMQ (AMQP)"
    participant W_AML as "Worker (AML)"
    participant Sanctions as "Sanctions API"
    participant DB as "PostgreSQL (ACID)"

    Note over Broker,DB: Path 3: External Timeout & Result Envelope Degradation
    Broker->>W_AML: Consume check_aml_watchlist
    W_AML->>Sanctions: POST /watchlists/check (Slow response / 504)
    W_AML->>W_AML: Timeout after 2.0s (Circuit Breaker tripping)
    W_AML->>W_AML: Synthesize ResultEnvelope(status='degraded', fallback_score=40)
    W_AML->>DB: UPDATE status='flagged_review', decision_reason='aml_watchlist_timeout'
    W_AML->>DB: INSERT operational_events (event_type='WATCHLIST_DEGRADED')
    W_AML->>W_AML: Observe queue lag & increment failure metric
```

### Path 4: Fatal Task Error & Errback Compensation
```mermaid
sequenceDiagram
    autonumber
    participant Broker as "RabbitMQ (AMQP)"
    participant W_Fast as "Worker (Scoring)"
    participant DB as "PostgreSQL (ACID)"

    Note over Broker,DB: Path 4: Fatal Task Error & link_error Handling
    Broker->>W_Fast: Consume evaluate_screening
    W_Fast->>W_Fast: Unrecoverable Database / Schema Exception
    W_Fast->>Broker: Trigger link_error(handle_screening_failure.s)
    Broker->>W_Fast: Consume handle_screening_failure
    W_Fast->>DB: UPDATE status='failed', decision_reason='fatal_worker_error'
    W_Fast->>W_Fast: Increment metric celery_tasks_failed_total{reason='unhandled'}
```

### Path 5: Idempotency Rejection (Duplicate Transaction)
```mermaid
sequenceDiagram
    autonumber
    actor Client as "Client Application"
    participant API as "FastAPI Gateway"
    participant Redis as "Redis 7 (L2 Cache)"
    participant DB as "PostgreSQL (ACID)"

    Note over Client,DB: Path 5: Atomic Idempotency Rejection
    Client->>API: POST /api/v1/screenings (Duplicate transaction_id)
    API->>Redis: SET NX EX (tx_id lock)
    alt Redis Key Exists
        Redis-->>API: Key already exists
    else Postgres Unique Constraint Collision
        API->>DB: INSERT INTO screenings
        DB-->>API: IntegrityError (uq_screenings_tx)
    end
    API->>DB: SELECT * FROM screenings WHERE transaction_id = tx_id
    API-->>Client: HTTP 200 OK (Existing screening record returned)
```

---

## 4. Observability & Telemetry Architecture

### 4.1 Prometheus Metric Registry (`/metrics`)
The system exposes standardized Prometheus metrics scraped via `/metrics`:

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `http_requests_total` | Counter | `method`, `endpoint`, `status` | Total incoming API ingestion requests. |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | Ingestion HTTP latency ($P_{50}, P_{95}, P_{99}$). |
| `celery_tasks_total` | Counter | `task_name`, `status` | Total Celery tasks executed across worker fleet. |
| `celery_task_duration_seconds` | Histogram | `task_name`, `queue` | Task execution runtime in seconds ($P_{50}, P_{95}, P_{99}$). |
| `celery_tasks_in_flight` | Gauge | `task_name`, `queue` | Currently executing tasks per child process. |
| `celery_queue_depth` | Gauge | `queue_name` | Number of ready/unacknowledged AMQP messages. |
| `celery_queue_message_age_seconds` | Gauge | `queue_name` | Age of oldest unacknowledged message in queue. |
| `celery_tasks_retried_total` | Counter | `task_name`, `reason` | Count of task retries due to transient errors. |

### 4.2 OpenTelemetry W3C TraceContext Propagation
* **Producer Propagation**:
  When FastAPI dispatches Celery tasks, the current OpenTelemetry span context is serialized using `TraceContextTextMapPropagator().inject(carrier)` and injected into Celery task headers (`headers={"traceparent": ...}`).
* **Consumer Extraction**:
  Worker `@signals.task_prerun` extracts the `traceparent` header to parent the worker span, creating a continuous distributed trace across `HTTP -> AMQP Queue -> Celery Worker -> Sanctions API`.

### 4.3 Structured Contextual Logging
Every log entry emits machine-readable JSON containing:
```json
{
  "timestamp": "2026-09-27T13:30:00.123Z",
  "level": "INFO",
  "logger": "services.worker.tasks.screening",
  "message": "screening_evaluation_completed",
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "task_id": "99887766-5544-3322-1100-aabbccddeeff",
  "queue": "fraud.screening.critical",
  "screening_id": "33445566-7788-99aa-bbcc-ddeeff001122",
  "duration_ms": 42.15,
  "risk_score": 12,
  "status": "approved"
}
```

### 4.4 Container Health Probes
* **Liveness (`/health/live`)**:
  Returns `HTTP 200 {"status": "alive"}` verifying the Python event loop is unblocked without polling downstream databases.
* **Readiness (`/health/ready`)**:
  Actively checks:
  1. PostgreSQL: `SELECT 1` via connection pool.
  2. Redis: `redis_client.ping()`.
  3. RabbitMQ: AMQP connection pre-ping.
  Returns `HTTP 200 {"status": "ready"}` or `HTTP 503 Service Unavailable`.

### 4.5 Graceful Worker Lifecycle (`SIGTERM`)
Celery workers register `@signals.worker_shutting_down`:
1. Cleanly releases acquired Redis distributed locks.
2. Closes and flushes SQLAlchemy async engine connection pools.
3. Allows in-flight idempotent tasks to commit or rollback cleanly without orphaned locks.

---

### 4.6 Unified Observability & Log Search Console: Grafana, Loki & Flower
The stack provisions a complete, zero-configuration SRE observability console:
* **Grafana Dashboard (`http://localhost:3000`)**:
  - Automatically provisioned with Prometheus and Loki datasources on container boot.
  - Pre-built dashboard `Fraud Screening & AML Observability` (`uid: fraud_screening_overview`) pre-configured with:
    - Real-time ingestion RPS and Celery task throughput gauges.
    - API Ingestion Latency Percentiles ({50}, P_{95}, P_{99}$).
    - Celery Task Runtime SLA ({95}, P_{99}$ by task).
    - Queue Depth Backpressure and Message Age tracking.
    - Live Searchable Log Panel with regex/keyword filter textbox.
  - Anonymous admin access enabled for instant exploration (`admin` / `admin`).
* **Grafana Loki Engine (`http://localhost:3100`) & Promtail Agent**:
  - Promtail connects via Docker socket to stream stdout/stderr JSON logs from all `fraud_*` containers directly into Loki.
  - Native LogQL filtering and JSON attribute extraction:
    ```logql
    # Search by correlation request ID across all workers
    {job="docker"} |= "a1b2c3d4" | json

    # Isolate all blocked or failed screening transactions
    {job="docker"} | json | status="blocked" or status="failure"

    # Identify slow screening tasks breaching 100ms SLA
    {job="docker"} | json | duration_ms > 100
    ```
* **Celery Flower Console (`http://localhost:5558`)**:
  - Worker process introspection, active child pools, broker queue lengths, and remote task revocation controls.

## 5. Operational Runbooks for SRE Operators

### Runbook A: Stuck Worker & Lock Deadlock Triage
* **Symptoms**: `celery_tasks_in_flight` remains non-zero for $> 30\text{ s}`; worker ceases consuming new messages.
* **Diagnostic Step 1**: Identify active worker tasks:
  ```bash
  celery -A services.worker.celery_app:celery_app inspect active
  ```
* **Diagnostic Step 2**: Inspect PostgreSQL locks:
  ```sql
  SELECT pid, query, state, age(clock_timestamp(), query_start) 
  FROM pg_stat_activity 
  WHERE state != 'idle';
  ```
* **Mitigation Step 3**: Revoke stuck task with termination signal:
  ```bash
  celery -A services.worker.celery_app:celery_app control revoke <TASK_ID> --terminate --signal=SIGKILL
  ```

### Runbook B: Queue Backpressure & Saturation Triage
* **Symptoms**: Prometheus alert `CeleryQueueLagBreach` fires; `celery_queue_message_age_seconds` exceeds 10s.
* **Diagnostic Step 1**: Check queue depths and consumer counts:
  ```bash
  celery -A services.worker.celery_app:celery_app inspect reserved
  ```
* **Mitigation Step 2**: Scale worker concurrency dynamically:
  ```bash
  celery -A services.worker.celery_app:celery_app control autoscale 8,2
  ```
* **Mitigation Step 3**: Tune prefetch count via worker configuration (`worker_prefetch_multiplier = 1`).

### Runbook C: Poison Pill & Dead Letter Queue (DLQ) Remediation
* **Symptoms**: `fraud.screening.dlq` depth increases; repeated retry storms in worker logs.
* **Diagnostic Step 1**: Inspect dead-letter messages without acknowledging:
  ```bash
  python3 scripts/inspect_dlq.py --queue fraud.screening.dlq --count 5
  ```
* **Mitigation Step 2**: Patch malformed payload or resolve upstream bug.
* **Mitigation Step 3**: Replay DLQ messages back to primary exchange:
  ```bash
  python3 scripts/replay_dlq.py --dlq fraud.screening.dlq --target-exchange fraud.direct
  ```

---

## 6. Incident Walkthrough Specification (The Evidence)

An automated walkthrough script (`scripts/incident_walkthrough.py`) simulates a production failure:
1. **The Trigger**: The sanctions partner API is injected with a 100% failure rate / 504 Gateway Timeout.
2. **The Alert**: Prometheus detects latency spike ($P_{99} \ge 2.0\text{ s}$) and queue message age exceeding threshold.
3. **The Triage**: The operator navigates Flower (`http://localhost:5555`) to observe task retries in `fraud.aml.bulk`.
4. **Root Cause Isolation**: Correlating `X-Request-ID` across structured logs identifies the HTTP 504 Gateway Timeout from the external sanctions URL.
5. **Operational Mitigation**: Operator enables the circuit-breaker fallback toggle via environment/configuration.
6. **Recovery**: Workers resume processing tasks in degraded mode (`status="flagged_review"`); queue drains back to 0; $P_{99}$ latency drops back below 120ms.

---

## 7. Project Milestones Breakdown

| Milestone | Scope & Deliverables | Primary Skills & Tools | Verification Gate |
| :--- | :--- | :--- | :--- |
| **Milestone 1** | Architectural specification, sequence diagrams, data models, SRE runbooks, and test plan (`docs/TEST_PLAN.md`). | `celery-doc`, `celery-commit` | `python3 scripts/verify_mermaid.py` passes with 0 errors. |
| **Milestone 2** | Container orchestration (`docker-compose.yml`), PostgreSQL schema (`init.sql`), service Dockerfiles, and minimal requirements. | `celery-commit` | Containers spin up healthy; schema initializes cleanly. |
| **Milestone 3** | Domain models, AMQP Kombu topology, Sanctions Watchlist Simulator API (`services/sanctions_api/`), Celery worker consumer (`services/worker/`), unit test suite (`tests/unit/`), worker debug profiles (`launch.json`). | `celery-test`, `celery-debug-setup` | Unit tests pass with 100% coverage; worker debug launchable. |
| **Milestone 4** | FastAPI Ingestion Gateway (`app/`), middlewares (correlation, error handling, profiling), producer dispatcher (`app/dispatcher.py`), `requests/requests.rest` workflows, and integration tests (`tests/integration/`). | `celery-debug-setup`, `celery-test` | Integration tests pass; `/docs` Swagger executes out-of-the-box. |
| **Milestone 5** | Prometheus metrics engine (`/metrics`), Flower dashboard, SRE triage runbooks, and automated incident walkthrough script (`scripts/incident_walkthrough.py`). | `celery-observability`, `celery-debug-setup` | Prometheus scrapes cleanly; incident walkthrough verifies recovery. |
| **Milestone 6** | Live multi-process distributed E2E test suite (`tests/e2e/test_live_e2e.py`) and capacity/contention latency benchmarks (`tests/benchmarks/`). Final 100% statement coverage validation. | `celery-test`, `celery-commit` | Full local CI pass (`./scripts/run_local_ci.sh -p 06_observability_and_operations --full`). |

---

## 8. Deliverables & Evidence Compliance Matrix

| Original Deliverable / Requirement | System Specification & Implementation | Verification Test Suite | Compliance Status |
| :--- | :--- | :--- | :---: |
| **1. Structured Logs** | Machine-parseable JSON logs containing `task_id`, `screening_id`, `request_id`, `queue`, `duration_ms`, and `outcome`. ContextVar propagation across API middlewares (`app/middlewares/correlation.py`) and Celery task headers (`app/dispatcher.py`). Structured logging in worker scoring and screening tasks (`services/worker/tasks/`). | `tests/integration/test_middlewares.py`<br>`tests/unit/test_scoring.py`<br>`tests/unit/test_screening_persistence.py` | **100% Verified** |
| **2. Metrics Engine** | Prometheus telemetry covering throughput (`celery_tasks_total`, `http_requests_total`), latency percentiles (`celery_task_duration_seconds`), in-flight tasks (`celery_tasks_in_flight`), retries (`celery_tasks_retried_total`), failures (`celery_tasks_total{status="failure"}`), queue depth (`celery_queue_depth`), and message age (`celery_queue_message_age_seconds`). Exposed at `GET /metrics`. | `tests/integration/test_metrics_endpoint.py`<br>`tests/unit/test_topology.py` | **100% Verified** |
| **3. Operational Dashboard** | Celery Flower dashboard containerized on `:5555` in `docker-compose.yml` for real-time worker introspection, active pools, broker queue depths, and remote task control. | `docker-compose.yml` / `docs/ARCHITECTURE_AND_STANDARDS.md` (§4) | **100% Verified** |
| **4. Operational Hygiene & Lifecycle** | Result expiration (`result_expires=3600`) in Celery configuration; dual-probe container health checks (`GET /health/live`, `GET /health/ready` testing PostgreSQL, Redis, and RabbitMQ); graceful worker SIGTERM shutdown closing connection pools (`services/worker/celery_app.py`). Log retention documented for container drivers. | `tests/unit/test_topology.py`<br>`tests/integration/test_health_probes.py`<br>`tests/unit/test_worker_lifecycle.py` | **100% Verified** |
| **5. Worker SRE Runbooks** | Comprehensive step-by-step triage runbooks for: (A) Stuck/hung workers & lock deadlocks, (B) Queue backpressure & saturation, and (C) Poison pills, retry storms & DLQ remediation. Includes inspection & replay CLI tools (`scripts/inspect_dlq.py`, `scripts/replay_dlq.py`). | `tests/unit/test_dlq_tools.py` (6 unit tests)<br>`docs/ARCHITECTURE_AND_STANDARDS.md` (§5) | **100% Verified** |
| **6. Incident Walkthrough (Evidence)** | Automated incident simulation script (`scripts/incident_walkthrough.py`) executing alert detection, Flower triage, log correlation via `X-Request-ID`, SRE circuit-breaker mitigation, recovery, and zero-data-loss validation. | `tests/unit/test_incident_walkthrough.py` (3 test scenarios covering end-to-end incident lifecycle) | **100% Verified** |
