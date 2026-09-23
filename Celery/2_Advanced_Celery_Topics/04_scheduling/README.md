# 04: Scheduling

Build a scheduled reporting and cleanup service with Celery Beat.

## Deliverables

- Periodic tasks with explicit timezone behavior.
- Idempotent report generation for each reporting period.
- A lock or durable uniqueness strategy for multiple Beat instances.
- Tests for missed schedules, duplicate delivery, and overlapping runs.

## Evidence

Document the scheduler deployment model and how you detect and recover from missed work.

---

## Project Definition: End-of-Day (EOD) Banking Cut-Off & Ledger Reconciliation Engine

Build a mission-critical financial scheduling and reconciliation service modeled after modern corporate banking platforms, treasury ledger systems, and payment institutions (e.g., **Stripe Treasury**, **Modern Treasury**, **Federal Reserve Fedwire/ACH Services**).

In commercial banking and fintech infrastructure, ledger accounts cannot remain open indefinitely. Every financial institution enforces an **End-of-Day (EOD) cut-off window**:
1. At **17:00 America/New_York** on banking days (Monday through Friday), the active business transaction ledger is sealed for the date `YYYY-MM-DD`.
2. All debits and credits posted prior to 17:00 are aggregated into an immutable financial period snapshot.
3. The internal ledger aggregates are cross-reconciled against simulated external clearinghouse settlement records.
4. An idempotent **Daily Reconciliation Report** is generated and signed with cryptographic totals.
5. In addition to daily financial closing, the scheduler executes automated **missed-period gap backfilling** after unexpected system downtime and runs a **nightly data retention cleanup** to purge expired idempotency keys and stale audit data.

### The Central Architectural Invariants
> 1. Financial scheduling must respect legal banking market timezones (`America/New_York`) across Daylight Saving Time (EST/EDT) boundaries without drift.
> 2. Daily reconciliation reports must be strictly idempotent: running repeatedly for the same business date must re-verify ledger balance without creating duplicate reports or double-counting transactions.
> 3. Redundant Celery Beat instances must coordinate via distributed locks to guarantee exactly-once schedule dispatching in multi-pod deployments.
> 4. Overlapping runs for the same reporting window must be blocked, and missed cut-offs after downtime must be detected and backfilled sequentially.

---

## 1. System Architecture

```mermaid
flowchart TD
    subgraph SchedulerTier ["1. High-Availability Scheduler Tier"]
        Beat1["Celery Beat Pod 1 (Primary)"]
        Beat2["Celery Beat Pod 2 (Standby)"]
        RedisLock["Redis Distributed Lock (Leader Lease)<br/>• Key: 'celery:beat:leader_lock'<br/>• TTL: 15s + Heartbeat Renewal"]
        Beat1 <-->|"Acquires Lease"| RedisLock
        Beat2 <-->|"Standby Lease Wait"| RedisLock
    end

    subgraph MessagingTier ["2. Driver & Broker Layer"]
        Broker["RabbitMQ Message Broker<br/>• Exchange: 'scheduling.direct'<br/>• Queues: 'reconciliation', 'cleanup'"]
        Beat1 -->|"Publishes crontab triggers"| Broker
    end

    subgraph WorkerTier ["3. Celery Consumer Fleet"]
        Worker["Celery Worker Fleet<br/>• Task: reconcile_eod_cutoff<br/>• Task: detect_and_backfill_gaps<br/>• Task: purge_expired_records"]
        Broker --> Worker
        TaskMutex["Redis Task Mutex<br/>• Key: 'lock:reconciliation:YYYY-MM-DD'<br/>• Prevents overlapping runs"]
        Worker <-->|"Acquires Mutex"| TaskMutex
    end

    subgraph StorageTier ["4. Persistent Durability Tier"]
        DB[("PostgreSQL 16 Engine<br/>• accounts<br/>• ledger_entries<br/>• reconciliation_reports [UNIQUE period_date]<br/>• idempotency_records")]
        Worker -->|"Aggregates entries & writes reports"| DB
    end

    subgraph IngestionControlPlane ["5. FastAPI Management & Audit Control Plane"]
        Client["Operations Client / REST Client"] -->|"HTTP API (Host Port 8000)"| API["FastAPI Application"]
        API -->|"Reads reports & manual triggers"| DB
        API -->|"Dispatches ad-hoc backfills"| Broker
    end
```

### Component Responsibilities

| Component | Responsibility |
| :--- | :--- |
| **Celery Beat (Leader-Elected)** | Evaluates periodic cron expressions in `America/New_York` timezone; acquires a distributed Redis leader lease to prevent redundant task dispatching across multi-replica deployments. |
| **RabbitMQ** | Delivers scheduled and ad-hoc task messages to specialized worker queues (`reconciliation`, `cleanup`). |
| **Celery Worker** | Consumes periodic triggers, acquires per-period execution locks, freezes ledger periods, aggregates minor-unit credits/debits, and generates reconciliation reports. |
| **PostgreSQL 16** | Stores double-entry ledger entries, accounts, signed daily reconciliation reports (enforcing `UNIQUE (period_date)`), and idempotency tracking records. |
| **Redis 7** | Acts as the Celery result backend, coordinates distributed Beat leader election (`celery:beat:leader_lock`), and manages task-level concurrency mutexes (`lock:reconciliation:{period_date}`). |
| **FastAPI** | Exposes operational REST endpoints for inspecting historical reconciliation reports, auditing unclosed period gaps, triggering manual backfills, and health checks. |

---

## 2. Deliverables Mapping

| Deliverable | Implementation in System |
| :--- | :--- |
| **Explicit Timezone & DST Behavior** | • Celery Beat configured with `timezone = "America/New_York"`.<br/>• Cut-off crontab: `crontab(hour=17, minute=0, day_of_week='mon-fri')`.<br/>• In EDT (Summer), fires at 21:00 UTC. In EST (Winter), fires at 22:00 UTC. Zero hour-drift across DST boundaries.<br/>• Database timestamps and internal storage remain strictly UTC. |
| **Idempotent Report Generation** | • Daily reports keyed by business date `YYYY-MM-DD`.<br/>• Database enforces `UNIQUE (period_date)`.<br/>• Re-running for an already-reconciled period performs an in-place verification update rather than creating duplicate entries. |
| **Durable Beat Uniqueness / Leader Lock** | • Multi-instance Beat protection using Redis atomic lease (`SET NX EX`) with periodic TTL renewal.<br/>• If the primary Beat instance terminates, standby Beat takes over within 15 seconds without duplicate dispatching. |
| **Overlapping Run Protection** | • Worker task acquires a Redis mutex `lock:reconciliation:{period_date}` with fencing token.<br/>• If a previous reconciliation is still processing, subsequent triggers gracefully defer or skip execution rather than colliding. |
| **Missed Schedule & Downtime Backfill** | • Scheduled heartbeat & startup detector queries PostgreSQL for unclosed business days between `last_reconciled_date` and `today`.<br/>• Sequentially dispatches missing daily reconciliation tasks in chronological order. |
| **Periodic Data Cleanup** | • Nightly cleanup task: `crontab(hour=2, minute=0)` in UTC.<br/>• Purges expired idempotency keys and transient audit logs older than the configured retention threshold (e.g. 30 days). |

---

## 3. Data Models & State Machine

```mermaid
erDiagram
    ACCOUNTS ||--o{ LEDGER_ENTRIES : contains
    RECONCILIATION_REPORTS ||--o{ LEDGER_ENTRIES : summarizes
    ACCOUNTS {
        uuid id PK
        string account_number UK
        string account_type
        bigint balance_cents
        char currency
        timestamp created_at
    }
    LEDGER_ENTRIES {
        uuid id PK
        uuid account_id FK
        bigint amount_cents
        string direction
        string status
        date period_date
        timestamp created_at
    }
    RECONCILIATION_REPORTS {
        uuid id PK
        date period_date UK
        bigint total_credits_cents
        bigint total_debits_cents
        bigint net_movement_cents
        bigint discrepancy_cents
        string status
        timestamp reconciled_at
        string verification_hash
    }
    IDEMPOTENCY_RECORDS {
        string key PK
        string scope
        timestamp expires_at
        timestamp created_at
    }
```

### Reconciliation Report State Machine

```mermaid
stateDiagram-v2
    [*] --> pending: Beat triggers 17:00 Cut-Off
    pending --> processing: Worker acquires lock & seals period
    processing --> balanced: Credits == Debits (Net Discrepancy = 0)
    processing --> discrepancy_detected: External clearing variance != 0
    processing --> failed: Unhandled database / network error
    failed --> processing: Manual or automated backfill retry
    discrepancy_detected --> manual_review: Escalated to compliance
    balanced --> [*]
    manual_review --> [*]
```

---

## 4. Sequence Diagrams (All Execution Paths)

### Path 1: Happy Path EOD Cut-off & Balanced Reconciliation

```mermaid
sequenceDiagram
    autonumber
    participant Beat as "Celery Beat (NY Time)"
    participant R_Lock as "Redis Leader Lock"
    participant Broker as "RabbitMQ Broker"
    participant Worker as "Celery Worker"
    participant DB as "PostgreSQL (ACID)"
    participant R_Task as "Redis Task Mutex"

    Note over Beat: 17:00 America/New_York (Mon-Fri)
    Beat->>R_Lock: Verify active leader lease
    R_Lock-->>Beat: Lease confirmed (Active Leader)
    Beat->>Broker: Publish reconcile_eod_cutoff(period_date='2026-09-23')
    Broker->>Worker: Deliver reconciliation task

    Worker->>R_Task: Acquire lock:reconciliation:2026-09-23 (TTL 60s)
    R_Task-->>Worker: Lock acquired

    Worker->>DB: Query ledger_entries for period_date='2026-09-23'
    DB-->>Worker: Aggregated Credits: 1,500,000 | Debits: 1,500,000

    Worker->>Worker: Verify Balance: Net Delta = 0 | Discrepancy = 0
    Worker->>DB: INSERT INTO reconciliation_reports (period_date, status='balanced')
    DB-->>Worker: Commit report

    Worker->>R_Task: Release lock:reconciliation:2026-09-23
    Worker-->>Broker: Acknowledge task completed
```

### Path 2: Discrepancy Detected During Clearing Reconciliation

```mermaid
sequenceDiagram
    autonumber
    participant Broker as "RabbitMQ Broker"
    participant Worker as "Celery Worker"
    participant DB as "PostgreSQL (ACID)"
    participant R_Task as "Redis Task Mutex"

    Broker->>Worker: Deliver reconcile_eod_cutoff(period_date='2026-09-23')
    Worker->>R_Task: Acquire lock:reconciliation:2026-09-23
    R_Task-->>Worker: Lock acquired

    Worker->>DB: Query ledger entries vs. clearinghouse settlement
    DB-->>Worker: Internal: 1,500,000 | Clearinghouse: 1,480,000
    Worker->>Worker: Detect Discrepancy: variance = 20,000 cents ($200.00)

    Worker->>DB: INSERT INTO reconciliation_reports (status='discrepancy_detected', discrepancy_cents=20000)
    DB-->>Worker: Commit report with audit discrepancy

    Worker->>R_Task: Release lock
    Worker-->>Broker: Acknowledge task completed (Flagged for Review)
```

### Path 3: Overlapping Run Prevention (Task Mutex)

```mermaid
sequenceDiagram
    autonumber
    participant Broker as "RabbitMQ Broker"
    participant Worker1 as "Celery Worker 1"
    participant Worker2 as "Celery Worker 2"
    participant R_Task as "Redis Task Mutex"

    Note over Worker1: Worker 1 is currently processing heavy period 2026-09-23
    Broker->>Worker2: Deliver duplicate / concurrent reconcile_eod_cutoff(2026-09-23)
    Worker2->>R_Task: Attempt acquire lock:reconciliation:2026-09-23
    R_Task-->>Worker2: Lock acquisition failed (Key already exists)

    Note over Worker2: Overlap detected! Skip redundant execution safely
    Worker2-->>Broker: Acknowledge message (Skipped without double-processing)
```

### Path 4: Missed Schedule & Downtime Backfill Recovery

```mermaid
sequenceDiagram
    autonumber
    participant Beat as "Celery Beat"
    participant Worker as "Celery Worker"
    participant DB as "PostgreSQL (ACID)"
    participant Broker as "RabbitMQ Broker"

    Note over Beat: System restarts after 48-hour outage
    Beat->>Broker: Publish detect_and_backfill_gaps()
    Broker->>Worker: Deliver gap detection task

    Worker->>DB: Query missing business days in reconciliation_reports
    DB-->>Worker: Missing periods: ['2026-09-21', '2026-09-22']

    loop For each missing business day (Chronological Order)
        Worker->>Broker: Enqueue reconcile_eod_cutoff(period_date)
    end
    Worker-->>Broker: Acknowledge gap detection complete
```

### Path 5: Nightly Idempotency & Audit Data Cleanup

```mermaid
sequenceDiagram
    autonumber
    participant Beat as "Celery Beat (UTC)"
    participant Broker as "RabbitMQ Broker"
    participant Worker as "Celery Worker"
    participant DB as "PostgreSQL (ACID)"

    Note over Beat: 02:00 UTC Daily (Off-peak cleanup)
    Beat->>Broker: Publish purge_expired_records(retention_days=30)
    Broker->>Worker: Deliver cleanup task

    Worker->>DB: DELETE FROM idempotency_records WHERE expires_at < NOW()
    DB-->>Worker: Deleted 12,450 expired keys
    Worker->>DB: Commit cleanup transaction
    Worker-->>Broker: Acknowledge cleanup completed
```

---

## 5. Scheduler Deployment Model & High Availability

In containerized and orchestrated environments (e.g. Kubernetes, Docker Compose):
1. **The Multi-Beat Problem**: Running multiple Celery Beat replicas for high availability leads to duplicate crontab dispatches unless a leader election mechanism coordinates them.
2. **Distributed Leader Lease Strategy**:
   - Each Beat pod attempts to acquire a Redis lease (`SET celery:beat:leader_lock <pod_id> NX EX 15`).
   - The primary instance runs a background heartbeat thread renewing the lease every 5 seconds.
   - If the active Beat pod crashes or loses network connectivity, the lease expires after 15 seconds.
   - The standby Beat pod acquires the lease and assumes scheduler duties with zero manual intervention.

---

## Completion Checklist

- [ ] Celery Beat crontab scheduled in `America/New_York` timezone for 17:00 cut-off.
- [ ] Explicit handling of Daylight Saving Time (EDT vs EST) verified by automated tests.
- [ ] Database unique constraint `UNIQUE (period_date)` enforces idempotent report generation.
- [ ] Re-running a completed period performs verification update without duplicate records.
- [ ] Redis distributed leader lock ensures single-active scheduler across multiple Beat instances.
- [ ] Redis task mutex prevents overlapping executions for the same reporting period.
- [ ] Gap detection task identifies missing past business days and sequentially triggers backfills.
- [ ] Nightly scheduled task purges expired idempotency records.
- [ ] FastAPI control plane exposes endpoints to inspect reports, trigger backfills, and seed test data.
- [ ] Pytest suite achieves 100% statement and branch coverage with Testcontainers.
- [ ] All Mermaid architectural diagrams validated with `python3 scripts/verify_mermaid.py`.
