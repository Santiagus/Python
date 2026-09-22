# Use Cases & Sequence Diagrams

This document details the primary end-to-end execution paths for the Multi-Rail Payment Orchestrator, illustrating task routing, worker queue bindings, contention isolation, and fault recovery.

---

## Use Case 1: Sub-Second Instant Payout (`critical` Queue Happy Path)

### Business Context
A gig worker taps "Cash Out Now" to receive funds immediately via FedNow / RTP / Visa Direct. The transaction must execute end-to-end with an SLA of $P_{99} < 100\text{ ms}$.

### Execution Flow
1. Client issues `POST /payments/instant` with an `Idempotency-Key` header and payment payload.
2. The FastAPI Gateway creates an initial payment record in PostgreSQL with status `pending`.
3. The API publishes `process_instant_payout` to exchange `payments.direct` with routing key `payment.instant.payout`.
4. RabbitMQ routes the message directly into the `critical` queue.
5. `worker_critical` (configured with `prefetch_multiplier=1` and `-O fair`) pulls the task immediately.
6. The worker acquires a row lock on the user's account, validates available minor-unit integer cents balance, and calls the Partner Bank Gateway.
7. The partner bank confirms fund clearance in $25\text{ ms}$.
8. The worker updates the payment status to `settled`, deducts balance, records the ledger entry, commits the database transaction, and acknowledges the AMQP message.
9. An asynchronous receipt task `send_payment_receipt` is published to the `default` queue so notification I/O does not block the real-time rail.
10. The client polls `GET /payments/{id}` or receives a websocket event confirming `settled` within $45\text{ ms}$ total elapsed time.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI Gateway
    participant DB as PostgreSQL
    participant B as RabbitMQ (payments.direct)
    participant WC as Worker Critical (-Q critical)
    participant Bank as Partner Bank Gateway
    participant WD as Worker Default (-Q default)

    C->>API: POST /payments/instant (Idempotency-Key: pay-101, amount: $250.00)
    API->>DB: Insert payment (status: pending, amount: 25000 cents)
    DB-->>API: Commit payment record
    API->>B: Publish process_instant_payout (queue: critical, priority: 9)
    API-->>C: 202 Accepted (payment_id: UUID, status: pending)

    Note over B,WC: Dedicated Worker Pool (prefetch=1, SLA < 100ms)
    B->>WC: Deliver process_instant_payout
    WC->>DB: SELECT account FOR UPDATE (Lock & verify balance)
    WC->>Bank: POST /v1/rails/rtp/transfers (instant clearing)
    Bank-->>WC: 200 OK (clearing_reference: "RTP-99412")
    WC->>DB: Update payment (status: settled) & balance update
    DB-->>WC: Commit transaction
    WC->>B: Publish send_payment_receipt (queue: default)
    WC-->>B: Acknowledge AMQP message (ACK)

    par Asynchronous Receipt on Default Queue
        B->>WD: Deliver send_payment_receipt
        WD->>WD: Format & send email notification
        WD-->>B: Acknowledge AMQP message (ACK)
    end

    C->>API: GET /payments/{id}
    API->>DB: Read payment status
    DB-->>API: Status: settled (latency: 42ms)
    API-->>C: 200 OK (status: settled, clearing_reference: RTP-99412)
```

---

## Use Case 2: Batch Payroll Disbursement with `.chunks(100)` (`bulk` Queue)

### Business Context
At 5:00 PM, an enterprise client uploads a monthly payroll run containing 10,000 disbursement instructions. The system must process all disbursements before midnight without degrading database performance or flooding the message broker.

### Execution Flow
1. Client submits `POST /disbursements/batch` with 10,000 employee payout instructions.
2. The API persists a master `batch_settlements` record and inserts 10,000 records in `disbursements` with status `queued`.
3. Instead of publishing 10,000 separate Celery messages, the application partitions the 10,000 disbursement IDs into **100 chunks of 100 items** using `.chunks(100)`:
   ```python
   process_payroll_chunk.chunks([(item_id,) for item_id in disbursement_ids], 100).apply_async(queue="bulk")
   ```
4. RabbitMQ receives only **100 compact messages** on the `bulk` queue instead of 10,000 individual task envelopes.
5. `worker_bulk` (configured with `prefetch_multiplier=4`) consumes chunks sequentially.
6. For each chunk of 100 items, the worker:
   - Performs a bulk SQL balance check across recipient accounts.
   - Executes a batched clearing call to the partner bank's bulk ACH endpoint.
   - Issues a single SQL `executemany()` to update all 100 records to `settled`.
   - Atomically increments the batch processed counter in PostgreSQL.
7. The worker acknowledges the chunk message.
8. Once all 100 chunks complete, the master batch status transitions to `completed`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Enterprise Client
    participant API as FastAPI Gateway
    participant DB as PostgreSQL
    participant B as RabbitMQ (bulk queue)
    participant WB as Worker Bulk (-Q bulk, prefetch=4)
    participant Bank as Partner Bank ACH Gateway

    C->>API: POST /disbursements/batch (10,000 payroll items)
    API->>DB: Insert batch_settlement & 10,000 disbursements (status: queued)
    DB-->>API: Commit batch transaction

    Note over API,B: Task Batching: 10,000 items -> 100 chunks of 100 items
    API->>B: Publish 100 chunk signatures (queue: bulk, routing_key: settlement.batch.payroll)
    API-->>C: 202 Accepted (batch_id: UUID, total_chunks: 100)

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
    C->>API: GET /disbursements/batch/{batch_id}
    API->>DB: Query batch status
    DB-->>API: Status: completed (10,000 / 10,000 settled)
    API-->>C: 200 OK (status: completed, duration: 42s)
```

---

## Use Case 3: System Under Contention (Bulk Saturation vs. Instant Payouts)

### Business Context
While `worker_bulk` is actively processing 50,000 pending disbursements (500 chunk messages saturating the `bulk` queue), a retail customer requests an instant FedNow payout. The system must prove **zero starvation** and maintain an SLA of $< 100\text{ ms}$.

### Execution Flow & Contention Proof
1. **The Contention State:** The `bulk` queue has 500 chunk messages waiting. `worker_bulk` processes chunks at maximum capacity ($C=2$, `prefetch_multiplier=4`).
2. A retail user triggers an instant payout via `POST /payments/instant`.
3. The task routes to the `critical` queue.
4. Because `worker_critical` is an **isolated process fleet** that only consumes from `-Q critical`, its worker processes are completely unaffected by the 500 messages queuing in `bulk`.
5. With `prefetch_multiplier=1`, `worker_critical` immediately takes the new instant payout message off the wire without waiting for any bulk task.
6. The instant payout completes in **$38\text{ ms}$**, proving that physical queue separation and prefetch tuning completely eliminate head-of-line blocking.

```mermaid
sequenceDiagram
    autonumber
    participant BulkClient as Enterprise Payroll System
    participant RetailClient as Retail Consumer
    participant API as FastAPI Gateway
    participant B as RabbitMQ
    participant WB as Worker Bulk (-Q bulk)
    participant WC as Worker Critical (-Q critical)
    participant DB as PostgreSQL

    Note over BulkClient,B: 50,000 Bulk Tasks Ingested (500 Chunks)
    BulkClient->>API: Submit 50k Payroll Batch
    API->>B: Enqueue 500 Chunk Messages into bulk queue
    Note over B,WB: bulk queue is 100% saturated (Depth: 500)
    B->>WB: WB consumes Chunk 1, Chunk 2, Chunk 3... (Busy)

    rect rgba(0, 120, 255, 0.08)
        Note over RetailClient,WC: Concurrent Real-Time Request Under Heavy Contention
        RetailClient->>API: POST /payments/instant (Instant Cashout)
        API->>B: Enqueue process_instant_payout into critical queue
        Note over B,WC: critical queue is completely isolated from bulk queue
        B->>WC: Deliver instant task immediately (Zero queuing delay!)
        WC->>DB: Lock account & update balance
        DB-->>WC: Commit
        WC-->>B: Acknowledge AMQP message (ACK)
        RetailClient->>API: GET /payments/{id}
        API-->>RetailClient: 200 OK: settled (Latency: 38ms - Zero SLA degradation!)
    end

    Note over B,WB: WB continues processing remaining 497 bulk chunks in background
```

---

## Use Case 4: Downstream Timeout, `soft_time_limit`, and DLQ Rejection

### Business Context
During an instant payment dispatch, the downstream partner bank's clearing rail hangs due to an upstream network partition. The system must catch the timeout before the client times out, gracefully release database locks, and reject the message to the **Dead-Letter Exchange (`payments.dlx`)**.

### Execution Flow
1. Client requests an instant payout.
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
    participant API as FastAPI Gateway
    participant B as RabbitMQ (critical)
    participant WC as Worker Critical
    participant DB as PostgreSQL
    participant Bank as Unresponsive Bank Gateway
    participant DLX as RabbitMQ (payments.dlx)
    participant QRej as Queue: rejected_payments

    API->>B: Publish process_instant_payout (soft_time_limit: 3s)
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

