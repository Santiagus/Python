# Use Cases & Sequence Diagrams

This document details the primary end-to-end execution paths for the Multi-Rail Payment Orchestrator, illustrating task routing, worker queue bindings, contention isolation, and fault recovery.

---

## Use Case 1: Sub-Second Instant Payout (`critical` Queue Happy Path)

### Business Context
A gig worker taps "Cash Out Now" to receive funds immediately via FedNow / RTP / Visa Direct. The transaction must execute end-to-end with an SLA of $P_{99} < 100\text{ ms}$.

### Execution Flow
1. Client issues `POST /payments/instant` with an `Idempotency-Key` header to the **Nginx Edge Gateway (`payment_gateway` on host port 8010)**.
2. Nginx evaluates semantic edge routing rules (`location /payments/instant`) and proxies the request to the dedicated real-time ingestion pool (**`api_instant:8000`**) over persistent HTTP/1.1 keep-alives (`keepalive 64;`).
3. `api_instant` validates the account in its local L1 memory cache (`_ACCOUNT_CACHE`, sub-microsecond), pre-generates the UUIDv4 primary key and UTC timestamp in memory, and issues a single SQL `INSERT` via **PgBouncer** without redundant `SELECT` or `await session.refresh()`.
4. PostgreSQL commits the payment record with status `pending` under strict `synchronous_commit = on` (requiring only 1 physical disk `fsync`).
5. `api_instant` publishes `process_instant_payout` to exchange `payments.direct` with routing key `payment.instant.payout`.
6. RabbitMQ routes the message directly into the `critical` queue.
7. `worker_critical` (configured with `prefetch_multiplier=1` and `-O fair`) pulls the task immediately.
8. The worker acquires a row lock on the user's account, validates available minor-unit integer cents balance, and calls the Partner Bank Gateway.
9. The partner bank confirms fund clearance in $25\text{ ms}$.
10. The worker updates the payment status to `settled`, deducts balance, records the ledger entry, commits the database transaction, and acknowledges the AMQP message.
11. An asynchronous receipt task `send_payment_receipt` is published to the `default` queue so notification I/O does not block the real-time rail.
12. The client polls `GET /payments/{id}` via Nginx Edge Gateway or receives a websocket event confirming `settled` within $45\text{ ms}$ total elapsed time.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant GW as Nginx Edge Gateway (Port 8010)
    participant API as FastAPI Instant Pool (api_instant:8000)
    participant PB as PgBouncer Multiplexer
    participant DB as PostgreSQL 16 (synchronous_commit=on)
    participant B as RabbitMQ (payments.direct)
    participant WC as Worker Critical (-Q critical)
    participant Bank as Partner Bank Gateway
    participant WD as Worker Default (-Q default)

    C->>GW: POST /payments/instant (Idempotency-Key: pay-101, amount: $250.00)
    Note over GW,API: Semantic Edge Routing -> upstream instant_backend
    GW->>API: Proxy via HTTP/1.1 Keep-Alive (X-Upstream-Addr: api_instant:8000)
    Note over API: 1. Validate account in L1 _ACCOUNT_CACHE (sub-microsecond)<br/>2. Pre-generate UUIDv4 & UTC timestamp (zero-refresh)
    API->>PB: Single SQL INSERT payment (status: pending, amount: 25000 cents)
    PB->>DB: Forward INSERT on pooled server connection
    DB-->>PB: Commit payment record (1 NVMe fsync)
    PB-->>API: Transaction committed
    API->>B: Publish process_instant_payout (queue: critical, priority: 9)
    API-->>GW: 202 Accepted (payment_id: UUID, status: pending)
    GW-->>C: 202 Accepted (X-Response-Time-Ms: 5.2)

    Note over B,WC: Dedicated Worker Pool (prefetch=1, SLA < 100ms)
    B->>WC: Deliver process_instant_payout
    WC->>PB: SELECT account FOR UPDATE (Lock & verify balance)
    PB->>DB: Forward query
    DB-->>PB: Account locked & balance returned
    PB-->>WC: Account locked & balance returned
    WC->>Bank: POST /v1/rails/rtp/transfers (instant clearing)
    Bank-->>WC: 200 OK (clearing_reference: "RTP-99412")
    WC->>PB: Update payment (status: settled) & balance update
    PB->>DB: Commit transaction
    DB-->>PB: Committed
    PB-->>WC: Committed
    WC->>B: Publish send_payment_receipt (queue: default)
    WC-->>B: Acknowledge AMQP message (ACK)

    par Asynchronous Receipt on Default Queue
        B->>WD: Deliver send_payment_receipt
        WD->>WD: Format & send email notification
        WD-->>B: Acknowledge AMQP message (ACK)
    end

    C->>GW: GET /payments/{id}
    GW->>API: Proxy to api_instant
    API->>PB: Read payment status
    PB->>DB: SELECT payment status
    DB-->>PB: Status: settled (latency: 42ms)
    PB-->>API: Status: settled
    API-->>GW: 200 OK (status: settled, clearing_reference: RTP-99412)
    GW-->>C: 200 OK
```

---

## Use Case 2: Batch Payroll Disbursement with `.chunks(100)` (`bulk` Queue)

### Business Context
At 5:00 PM, an enterprise client uploads a monthly payroll run containing 10,000 disbursement instructions. The system must process all disbursements before midnight without degrading database performance or flooding the message broker.

### Execution Flow
1. Enterprise Client submits `POST /disbursements/batch` with 10,000 employee payout instructions to the **Nginx Edge Gateway (`payment_gateway` on host port 8010)**.
2. Nginx evaluates semantic edge routing rules (`location /disbursements/batch`) and routes the payload to the dedicated batch ingestion container pool (**`api_batch:8000`**), insulating the real-time API from CPU JSON parsing spikes.
3. `api_batch` persists a master `batch_settlements` record and inserts 10,000 records in `disbursements` with status `queued` using direct SQL batch insertion.
4. Instead of publishing 10,000 separate Celery messages, `api_batch` partitions the 10,000 disbursement IDs into **100 chunks of 100 items** using `.chunks(100)`:
   ```python
   process_payroll_chunk.chunks([(item_id,) for item_id in disbursement_ids], 100).apply_async(queue="bulk")
   ```
5. RabbitMQ receives only **100 compact messages** on the `bulk` queue instead of 10,000 individual task envelopes.
6. `worker_bulk` (configured with `prefetch_multiplier=4`) consumes chunks sequentially.
7. For each chunk of 100 items, the worker:
   - Performs a bulk SQL balance check across recipient accounts.
   - Executes a batched clearing call to the partner bank's bulk ACH endpoint.
   - Issues a single SQL `executemany()` to update all 100 records to `settled`.
   - Atomically increments the batch processed counter in PostgreSQL.
8. The worker acknowledges the chunk message.
9. Once all 100 chunks complete, the master batch status transitions to `completed`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Enterprise Client
    participant GW as Nginx Edge Gateway (Port 8010)
    participant API as FastAPI Batch Pool (api_batch:8000)
    participant DB as PostgreSQL
    participant B as RabbitMQ (bulk queue)
    participant WB as Worker Bulk (-Q bulk, prefetch=4)
    participant Bank as Partner Bank ACH Gateway

    C->>GW: POST /disbursements/batch (10,000 payroll items)
    Note over GW,API: Semantic Edge Routing -> upstream batch_backend
    GW->>API: Proxy via HTTP/1.1 Keep-Alive (X-Upstream-Addr: api_batch:8000)
    API->>DB: Insert batch_settlement & 10,000 disbursements (status: queued)
    DB-->>API: Commit batch transaction

    Note over API,B: Task Batching: 10,000 items -> 100 chunks of 100 items
    API->>B: Publish 100 chunk signatures (queue: bulk, routing_key: settlement.batch.payroll)
    API-->>GW: 202 Accepted (batch_id: UUID, total_chunks: 100)
    GW-->>C: 202 Accepted (X-Response-Time-Ms: 14.8)

    loop Process 100 Chunks
        B->>WB: Deliver process_payroll_chunk (Chunk K: 100 items)
        WB->>DB: Bulk SELECT accounts FOR UPDATE (100 accounts)
        WB->>Bank: POST /v1/rails/ach/batches (100 payments payload)
        Bank-->>WB: 200 OK (batch_confirmation: "ACH-BATCH-551")
        WB->>DB: executemany UPDATE disbursements (status: settled)
        WB->>DB: UPDATE batch_settlements SET processed_chunks = processed_chunks + 1
        DB-->>WB: Commit batch chunk
        WB-->>B: Acknowledge AMQP message (ACK)
    end

    Note over DB: When processed_chunks == total_chunks -> status = completed
    C->>GW: GET /disbursements/batch/{batch_id}
    GW->>API: Proxy to api_batch
    API->>DB: Query batch status
    DB-->>API: Status: completed (10,000 / 10,000 settled)
    API-->>GW: 200 OK (status: completed, duration: 42s)
    GW-->>C: 200 OK
```

---

## Use Case 3: System Under Contention (Bulk Saturation vs. Instant Payouts)

### Business Context
While enterprise clients upload large payroll runs (50,000 pending disbursements saturating both batch ingestion and worker capacity), a retail customer requests an instant FedNow payout. The system must prove **zero starvation** across both API ingestion and background task execution, maintaining an SLA of $P_{99} < 100\text{ ms}$.

### Execution Flow & Contention Proof (Dual-Layer Isolation)
1. **The Dual Contention State:**
   - **Ingestion Layer:** 50,000 bulk disbursement items are submitted concurrently. The **Nginx Edge Gateway (Port 8010)** routes this traffic strictly to the dedicated **`api_batch:8000`** container pool. The real-time container pool (**`api_instant:8000`**) experiences 0% CPU parsing load and zero event-loop lag.
   - **Execution Layer:** 500 chunk messages saturate the `bulk` queue. `worker_bulk` processes chunks at maximum capacity ($C=2$, `prefetch_multiplier=4`).
2. A retail user triggers an instant payout via `POST /payments/instant` against Nginx on port 8010.
3. Nginx proxies to `api_instant:8000` via persistent keep-alives; the request is validated, inserted, and published to RabbitMQ in **$5.2\text{ ms}$**.
4. The task routes to the `critical` queue in exchange `payments.direct`.
5. Because `worker_critical` is an **isolated process fleet** that only consumes from `-Q critical`, its worker processes are completely unaffected by the 500 messages queuing in `bulk`.
6. With `prefetch_multiplier=1` and `-O fair`, `worker_critical` immediately takes the new instant payout message off the wire without waiting for any bulk task.
7. The instant payout completes in **$38\text{ ms}$**, proving that physical isolation at **both tiers** (Edge Ingestion Pools + Consumer Worker Fleets) completely eliminates head-of-line blocking.

```mermaid
sequenceDiagram
    autonumber
    participant BulkClient as Enterprise Payroll System
    participant RetailClient as Retail Consumer
    participant GW as Nginx Edge Gateway (Port 8010)
    participant APIB as FastAPI Batch (api_batch:8000)
    participant APII as FastAPI Instant (api_instant:8000)
    participant B as RabbitMQ
    participant WB as Worker Bulk (-Q bulk)
    participant WC as Worker Critical (-Q critical)
    participant DB as PostgreSQL

    Note over BulkClient,WB: Layer 1 Contention: 50,000 Bulk Tasks Ingested
    BulkClient->>GW: POST /disbursements/batch (50k Payroll Batch)
    GW->>APIB: Semantic Routing -> api_batch:8000 (Isolated Event Loop)
    APIB->>B: Enqueue 500 Chunk Messages into bulk queue
    Note over B,WB: bulk queue is 100% saturated (Depth: 500)
    B->>WB: WB consumes Chunk 1, Chunk 2, Chunk 3... (Busy)

    rect rgba(0, 120, 255, 0.08)
        Note over RetailClient,WC: Concurrent Real-Time Request Under Heavy Contention
        RetailClient->>GW: POST /payments/instant (Instant Cashout)
        GW->>APII: Semantic Routing -> api_instant:8000 (100% Idle & Responsive!)
        APII->>B: Enqueue process_instant_payout into critical queue (5.2ms ingestion)
        Note over B,WC: critical queue is completely isolated from bulk queue
        B->>WC: Deliver instant task immediately (Zero queuing delay!)
        WC->>DB: Lock account & update balance
        DB-->>WC: Commit
        WC-->>B: Acknowledge AMQP message (ACK)
        RetailClient->>GW: GET /payments/{id}
        GW->>APII: Proxy to api_instant
        APII-->>GW: 200 OK: settled (Latency: 38ms)
        GW-->>RetailClient: 200 OK (Zero SLA degradation!)
    end

    Note over B,WB: WB continues processing remaining 497 bulk chunks in background
```

---

## Use Case 4: Downstream Timeout, `soft_time_limit`, and DLQ Rejection

### Business Context
During an instant payment dispatch, the downstream partner bank's clearing rail hangs due to an upstream network partition. The system must catch the timeout before the client times out, gracefully release database locks, and reject the message to the **Dead-Letter Exchange (`payments.dlx`)**.

### Execution Flow
1. Client requests an instant payout via the **Nginx Edge Gateway (Port 8010)**, routed to `api_instant`.
2. The task is routed to `worker_critical` (`soft_time_limit=3s`, `time_limit=5s`).
3. The worker acquires the row lock on the user's account and issues an HTTP call to the partner bank gateway.
4. The partner bank hangs. At $t = 3.0\text{ s}$, the Python runtime raises `celery.exceptions.SoftTimeLimitExceeded`.
5. The task catches `SoftTimeLimitExceeded`:
   - Executes an explicit database rollback, releasing the row lock on the user's account.
   - Updates the payment status in PostgreSQL to `timed_out` with `error_reason="Upstream partner bank timeout exceeding 3000ms"`.
   - Rejects the AMQP message using `self.retry()` exhaustion or `reject(requeue=False)`.
6. RabbitMQ intercepts the rejected message and routes it to `payments.dlx` via `x-dead-letter-exchange`.
7. The dead-letter exchange routes the message into the `rejected_payments` queue for automated alerting and audit review.
8. The worker child process remains healthy and immediately resumes processing subsequent transactions without being terminated by kernel SIGKILL.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant GW as Nginx Edge Gateway (Port 8010)
    participant API as FastAPI Instant (api_instant:8000)
    participant B as RabbitMQ (critical)
    participant WC as Worker Critical
    participant DB as PostgreSQL
    participant Bank as Unresponsive Bank Gateway
    participant DLX as RabbitMQ (payments.dlx)
    participant QRej as Queue: rejected_payments

    C->>GW: POST /payments/instant
    GW->>API: Proxy to api_instant
    API->>B: Publish process_instant_payout (soft_time_limit: 3s)
    API-->>GW: 202 Accepted
    GW-->>C: 202 Accepted

    B->>WC: Deliver task to worker child
    WC->>DB: BEGIN & SELECT account FOR UPDATE (Row locked)
    WC->>Bank: POST /v1/rails/rtp/transfers (Connecting...)
    Note over Bank: Upstream network partition: Gateway hangs indefinitely

    Note over WC: t = 3.0s: SoftTimeLimitExceeded raised by Celery
    WC->>WC: Catch SoftTimeLimitExceeded exception
    WC->>DB: ROLLBACK (Releases account lock immediately)
    WC->>DB: UPDATE payments SET status = 'timed_out', error = 'Upstream timeout > 3s'
    DB-->>WC: Commit failure status
    WC->>B: Basic.Nack / Reject (requeue=False)

    Note over B,DLX: x-dead-letter-exchange intercepts rejected message
    B->>DLX: Forward rejected message (routing_key: payment.rejected)
    DLX->>QRej: Enqueue message for audit inspection & operational alerting
    WC->>WC: Worker child process recycles cleanly (Ready for next task)
```

---

## Use Case 5: Cluster-Wide Account Mutation with Instant L1 Cache Invalidation via Redis Pub/Sub

### Business Context
In a horizontally scaled distributed API fleet (Kubernetes pods or ECS tasks behind an Nginx edge load balancer), each container maintains an L1 process-local in-memory cache (`_ACCOUNT_CACHE`) to validate account existence in sub-microsecond time. When an account is mutated or frozen (e.g. due to KYC suspension, court garnishment, or fraudulent activity) on Pod A, all other API pods (Pod B, Pod C) must immediately invalidate their local L1 cache to eliminate stale-read hazards without waiting for the default 300s TTL.

### Execution Flow
1. An compliance officer or administrative system issues an account status change or manual cache invalidation via `POST /accounts/{account_id}/invalidate-cache` routed to **API Pod A**.
2. **Pod A** evicts its local L1 `_ACCOUNT_CACHE` entry immediately.
3. **Pod A** publishes an AMQP/Redis broadcast event on channel `account:invalidations` with payload `{"account_id": "<uuid>", "source": "api_pod_a"}`.
4. The Redis Pub/Sub broker fans out the message to all active subscriber listeners across the cluster.
5. **API Pod B's** background `AccountCacheManager` listener task consumes the message from Redis Pub/Sub.
6. **Pod B** immediately purges the account UUID from its process-local memory (`_ACCOUNT_CACHE.pop(account_id)`).
7. A subsequent instant payout request arriving at **Pod B** misses the L1 cache, issues a fresh query to PostgreSQL via PgBouncer, verifies the updated account status, and rejects the unauthorized transaction immediately.

```mermaid
sequenceDiagram
    autonumber
    participant Admin as Compliance / Risk Engine
    participant PodA as API Gateway (Pod A)
    participant Redis as Redis Pub/Sub Broker
    participant PodB as API Gateway (Pod B)
    participant Client as User / Payer
    participant DB as PostgreSQL (ACID Core)

    Admin->>PodA: POST /accounts/{id}/invalidate-cache (Account Frozen)
    PodA->>PodA: Evict L1 _ACCOUNT_CACHE locally (instant)
    PodA->>Redis: PUBLISH account:invalidations {"account_id": "acc-123"}
    PodA-->>Admin: 200 OK {"invalidated": true, "cluster_notified": true}

    Note over Redis,PodB: Asynchronous Sub-Millisecond Event Fan-Out
    Redis-->>PodB: Broadcast event: account:invalidations "acc-123"
    PodB->>PodB: Background listener pops "acc-123" from local L1 cache

    rect rgba(0, 120, 255, 0.08)
        Note over Client,DB: Subsequent Request Hits Pod B
        Client->>PodB: POST /payments/instant (Source: acc-123)
        PodB->>PodB: Check L1 memory: Cache MISS!
        PodB->>DB: Query account status via PgBouncer
        DB-->>PodB: Status: FROZEN / SUSPENDED
        PodB-->>Client: 403 Forbidden: Account suspended (Zero stale-read risk!)
    end
```

---

## Use Case 6: Partner Bank Rail Outage with Distributed Circuit Breaker & Automatic Rail Failover

### Business Context
Instant payouts depend on real-time external bank settlement rails (RTP, FedNow). When an upstream rail experiences brownouts, severe latency spikes, or elevated 5xx error rates, unconstrained retries exhaust worker thread pools and hold database locks. The system must automatically trip a distributed circuit breaker, fail fast on the degraded rail, and seamlessly divert transactions to an alternate healthy clearing rail (e.g. fallback from RTP to FedNow) without worker downtime or manual intervention.

### Execution Flow
1. Under normal operation, instant payouts dispatch over the primary clearing rail (`rtp`).
2. The partner bank simulator begins returning 500 errors or timing out. The client records these failures in Redis.
3. Within a rolling 30-second window, the failure rate exceeds 50% ($N \ge 5$). The distributed circuit breaker transitions from `CLOSED` to `OPEN`.
4. Worker child process receives an instant payout task for account `acc-123` on rail `rtp`.
5. Worker verifies `circuit_breaker.allow_request("rtp")`, which immediately raises `CircuitBreakerOpenError` (sub-millisecond fast-fail, no external HTTP socket opened).
6. Worker catches `CircuitBreakerOpenError` and queries `get_fallback_rail("rtp")`, resolving to `fednow`.
7. Worker checks `circuit_breaker.allow_request("fednow")`, which reports `CLOSED` (healthy).
8. Worker redirects the payment to the FedNow rail; the bank clears the transaction in $35\text{ ms}$.
9. Worker updates PostgreSQL: payment status is `settled`, `clearing_rail="fednow"`, and `fallback_applied=true`.
10. If all fallback rails are `OPEN`, the task issues a fast-fail compensating refund, restores ledger balance, and marks status as `failed` without holding worker threads.

```mermaid
sequenceDiagram
    autonumber
    participant WC as Worker Critical (-Q critical)
    participant Redis as Redis (Circuit Breaker State)
    participant RTP as Bank Rail (RTP - Outage)
    participant FedNow as Bank Rail (FedNow - Healthy)
    participant DB as PostgreSQL (Ledger)

    Note over RTP: Partner RTP Rail brownout: 50%+ 5xx errors
    Note over Redis: Circuit State for "rtp" transitions to OPEN

    WC->>Redis: allow_request("rtp")
    Redis-->>WC: CircuitBreakerOpenError ("rtp circuit is OPEN")

    rect rgba(0, 200, 100, 0.08)
        Note over WC,FedNow: Automated Dynamic Rail Failover
        WC->>WC: Catch CircuitBreakerOpenError -> resolve fallback: "fednow"
        WC->>Redis: allow_request("fednow")
        Redis-->>WC: Allowed (State: CLOSED)
        WC->>FedNow: POST /v1/rails/fednow/transfers (Fast clearance)
        FedNow-->>WC: 200 OK {"settlement_id": "tx_fn_992", "status": "settled"}
        WC->>DB: UPDATE payments SET status = 'settled', rail = 'fednow', fallback = true
        DB-->>WC: Commit
    end

    Note over Redis,RTP: Periodic Canary Probing in HALF_OPEN State
    Note over WC: After 30s reset timeout, single canary probe tests RTP
    alt Canary Probe Succeeds
        WC->>RTP: Probe Request
        RTP-->>WC: 200 OK
        WC->>Redis: record_success("rtp") -> Transition to CLOSED
    else Canary Probe Fails
        WC->>RTP: Probe Request (Fails)
        WC->>Redis: record_failure("rtp") -> Re-open circuit for 30s
    end
```

---

## Use Case 7: Automated CI/CD Contention & Capacity Regression Gate

### Business Context
In financial systems, minor ORM query alterations, unbudgeted database connection pooling, or middleware additions can silently degrade real-time ingestion latency under background load. To prevent regressions from reaching staging or production, an automated Contention Regression Gate runs as a mandatory CI/CD pipeline stage, subjecting an ephemeral distributed stack to concurrent ingestion contention and evaluating strict SLA gates.

### Execution Flow
1. A developer creates a Pull Request modifying API routing, database models, or Celery task definitions.
2. GitHub Actions CI initializes an ephemeral distributed stack via `docker compose`: PgBouncer, PostgreSQL, RabbitMQ, Redis, 2 API containers, and 3 worker daemons.
3. The pipeline executes `scripts/ci_contention_gate.py --rate 150 --duration 10`.
4. The test harness initiates background batch payroll uploads (700 disbursements across 7 batches) to saturate the `bulk` queue and worker capacity.
5. Simultaneously, the harness dispatches 1,500 real-time payments paced via Little's Law ($150\text{ req/s}$ arrival rate) against the API gateway.
6. The test runner measures client-side HTTP latency percentiles and inspects PgBouncer active connection pools.
7. The runner evaluates the 4 mandatory SLA gates:
   - **Gate 1 ($P_{99}$ Tail Latency):** Measured $56.66\text{ ms} \le 100.00\text{ ms}$ (PASSED).
   - **Gate 2 (Error Rate):** Measured $0.00\% = 0.00\%$ (PASSED).
   - **Gate 3 (DB Connections):** Measured $22 \le 26$ (PASSED).
   - **Gate 4 (Degradation vs. Baseline):** Measured $-31.7\% \le +15.0\%$ (PASSED).
8. The runner generates a JSON report (`reports/benchmarks/ci_gate_<timestamp>.json`) and an ASCII audit summary. The PR gate succeeds and allows merge.

```mermaid
sequenceDiagram
    autonumber
    participant CI as GitHub Actions Runner
    participant Docker as Ephemeral Docker Compose Fleet
    participant Gate as Contention Gate Harness (ci_contention_gate.py)
    participant Nginx as Edge Gateway (Port 8010)
    participant PgB as PgBouncer
    participant DB as PostgreSQL

    CI->>Docker: docker compose up -d (PgBouncer, Postgres, RabbitMQ, Redis, APIs, Workers)
    Docker-->>CI: Services healthy & listening

    CI->>Gate: Execute ci_contention_gate.py --rate 150 --duration 10
    Gate->>Nginx: Background: POST /disbursements/batch (Saturate bulk queue)
    Gate->>Nginx: Foreground: 1,500 Instant Payments (Little's Law: 150 req/s)

    Note over Gate,Nginx: Real-time latency measurement across 1,500 requests

    Gate->>PgB: Inspect active server connections (SHOW POOLS)
    PgB-->>Gate: Active connections: 22 / 26 budgeted ceiling

    Gate->>Gate: Evaluate SLA Gates:
    Note over Gate: Gate 1 (P99 <= 100ms): 56.66ms [PASSED]<br/>Gate 2 (Error Rate == 0%): 0.00% [PASSED]<br/>Gate 3 (DB Conns <= 26): 22 conns [PASSED]<br/>Gate 4 (Degradation <= +15%): -31.7% [PASSED]

    Gate->>CI: Exit Code 0 (ALL GATES PASSED)
    CI->>CI: Mark GitHub Actions Check as SUCCESS
```



