# Distributed Sequence Diagrams (All Execution & Failure Paths)

> **Module**: `07_failure_recovery_lab`  
> **System**: High-Value Interbank Wire & Treasury Settlement Gateway  
> **Standards Compliance**: Celery 5.4, RabbitMQ 3.13 AMQP 0-9-1, PostgreSQL 16 ACID  

This document formalizes the distributed sequence diagrams covering **all normal, degraded, and failure execution paths** across the wire settlement lifecycle.

---

## 1. Path 1: Normal Wire Submission & Settlement (Happy Path)

Demonstrates the zero-refresh, publisher-confirmed ingestion and late-ack settlement workflow.

```mermaid
sequenceDiagram
    autonumber
    actor Client as "Treasury Client"
    participant API as "FastAPI Gateway (:8000)"
    participant DB as "PostgreSQL 16 (ACID)"
    participant Broker as "RabbitMQ 3.13 (wire.direct)"
    participant Worker as "Celery Worker (Pod 1)"
    participant Bank as "Bank Simulator API (:8010)"

    Note over Client,Bank: Path 1: Happy Path Wire Execution
    Client->>API: POST /api/v1/wires (Payload + Idempotency-Key)
    API->>API: Generate wire_id (UUID4) & calculate amount_cents
    API->>DB: INSERT into wire_transfers (status='processing')
    DB-->>API: Commit successful
    API->>Broker: Basic.Publish (wire.settlement.critical, delivery_mode=2)
    Broker-->>API: Basic.Ack (Publisher Confirm)
    API-->>Client: HTTP 202 Accepted {wire_id, status: 'processing'}

    Broker->>Worker: Basic.Deliver (wire_task, redelivered=False)
    Worker->>DB: SELECT FOR UPDATE FROM wire_transfers WHERE wire_id = ?
    Worker->>Bank: GET /api/v1/fedwire/disburse/{idempotency_key}
    Bank-->>Worker: 404 Not Found (Not yet executed)
    Worker->>Bank: POST /api/v1/fedwire/disburse (Wire Payload)
    Bank-->>Worker: 200 OK {bank_reference_id: "FED-WIRE-99214"}
    Worker->>DB: UPDATE wire_transfers SET status='settled', bank_ref=...
    Worker->>DB: INSERT into ledger_journal (DEBIT, CREDIT entries)
    DB-->>Worker: Commit successful
    Worker->>Broker: Basic.Ack (DeliveryTag)
```

---

## 2. Path 2: Worker Hard Crash (`SIGKILL`) & Redelivery Recovery (`acks_late=True`)

Illustrates the core problem: worker killed *after* external disbursement but *before* database commit and ACK. Proves two-phase idempotency eliminates double-disbursement upon redelivery.

```mermaid
sequenceDiagram
    autonumber
    actor Chaos as "Chaos Harness (scripts/chaos_harness.py)"
    participant Broker as "RabbitMQ (wire.direct)"
    participant W1 as "Worker Pod 1 (Crash Target)"
    participant W2 as "Worker Pod 2 (Surviving Pod)"
    participant DB as "PostgreSQL 16"
    participant Bank as "Bank Simulator API (:8010)"

    Note over Broker,Bank: Stage 1: Worker Execution & Abrupt Hard Crash
    Broker->>W1: Basic.Deliver (wire_task, redelivered=False)
    W1->>DB: Acquire row lock (SELECT FOR UPDATE)
    W1->>Bank: POST /api/v1/fedwire/disburse (Wire Payload)
    Bank-->>W1: 200 OK {bank_reference_id: "FED-WIRE-77312"}
    
    Note over Chaos,W1: CHAOS INJECTION: kill -9 W1 (SIGKILL)
    Chaos->>W1: SIGKILL (Hard process crash)
    Note over W1: Process terminates abruptly. Socket closes.
    Note over DB: PostgreSQL detects severed TCP connection -> Aborts TX & Releases Lock
    
    Broker->>Broker: AMQP channel closed without Basic.Ack
    Broker->>Broker: Re-queue message at head of queue (redelivered=True)

    Note over Broker,Bank: Stage 2: Surviving Worker Consumes Redelivered Task
    Broker->>W2: Basic.Deliver (wire_task, redelivered=True)
    W2->>DB: SELECT FOR UPDATE FROM wire_transfers WHERE wire_id = ?
    W2->>Bank: GET /api/v1/fedwire/disburse/{idempotency_key}
    Bank-->>W2: 200 OK {bank_reference_id: "FED-WIRE-77312"} (ALREADY EXECUTED!)
    Note over W2: Phase 1 Check: External Wire Already Disbursed! Bypassing Phase 2!
    W2->>DB: UPDATE wire_transfers SET status='settled', redelivered_flag=TRUE
    W2->>DB: INSERT into ledger_journal (DEBIT, CREDIT entries)
    DB-->>W2: Commit successful
    W2->>Broker: Basic.Ack (DeliveryTag)
    Note over W2,Bank: Result: Zero Duplicate Payouts! Exact Ledger Parity!
```

---

## 3. Path 3: The Early Ack Failure Mode (`acks_late=False`) - Silent Data Loss

Proves why default Celery early acknowledgements must never be used in financial applications.

```mermaid
sequenceDiagram
    autonumber
    actor Chaos as "Chaos Injector"
    participant Broker as "RabbitMQ Broker"
    participant Worker as "Celery Worker (acks_late=False)"
    participant DB as "PostgreSQL 16"
    participant Bank as "Bank Simulator API"

    Note over Broker,Bank: Path 3: The Early Ack Silent Loss Failure Mode
    Broker->>Worker: Basic.Deliver (wire_task)
    Worker->>Broker: Basic.Ack (IMMEDIATE EARLY ACKNOWLEDGEMENT)
    Note over Broker: Broker removes message from queue. Message is GONE.
    
    Worker->>DB: Acquire row lock & begin work
    
    Note over Chaos,Worker: CHAOS INJECTION: kill -9 Worker
    Chaos->>Worker: SIGKILL
    Note over Worker: Worker dies. Memory lost.
    Note over DB: Database transaction rolls back.
    
    Note over Broker,DB: POST-MORTEM: Broker has NO record of message.<br/>Database status is stuck indefinitely in 'processing'.<br/>No surviving worker will ever execute the wire.<br/>RESULT: SILENT CAPITAL & TRANSACTION LOSS!
```

---

## 4. Path 4: Broker Hard Crash & Reconnect / Recovery

Proves that durable exchanges, persistent messages (`delivery_mode=2`), and publisher confirms survive complete broker failure without data loss.

```mermaid
sequenceDiagram
    autonumber
    actor Client as "Chaos Load Generator"
    participant API as "FastAPI Gateway"
    participant Broker as "RabbitMQ Container"
    participant Disk as "RabbitMQ NVMe WAL Storage"
    participant Worker as "Celery Worker Fleet"

    Note over Client,Worker: Path 4: Broker Hard Crash & Recovery
    Client->>API: Rapid Ingestion (100 req/s)
    API->>Broker: Basic.Publish (delivery_mode=2)
    Broker->>Disk: fsync to write-ahead log
    Broker-->>API: Basic.Ack (Publisher Confirm)

    Note over Broker: CHAOS: docker kill rabbitmq
    Broker->>Broker: Abrupt Container Termination
    
    API->>Broker: Basic.Publish (Next batch)
    API--xBroker: ConnectionRefusedError
    API-->>Client: HTTP 503 Service Unavailable (with Retry-After: 5s)
    
    Note over Worker: Worker heartbeat fails (AMQPHeartbeatTimeout).<br/>Workers enter exponential reconnection backoff.

    Note over Broker: RECOVERY: docker start rabbitmq
    Broker->>Disk: Replay persistent journal from disk
    Broker->>Broker: Re-instantiate durable queues with 100% messages intact
    
    Worker->>Broker: Reconnect & re-open AMQP channels
    Broker->>Worker: Deliver queued persistent messages
    Worker->>Worker: Process and settle all wire orders
    Note over Client,Worker: Result: Zero Messages Lost. Full Ingestion Recovery.
```

---

## 5. Path 5: Poison Pill Malformed Payload & DLX/DLQ Dead-Letter Handling

Demonstrates the quarantine of corrupt or unrecoverable wire payloads without blocking critical queues or triggering infinite crash loops.

```mermaid
sequenceDiagram
    autonumber
    actor Malicious as "Corrupt Payload Injector"
    participant API as "FastAPI Gateway"
    participant Broker as "RabbitMQ (wire.settlement.critical)"
    participant DLX as "Dead Letter Exchange (wire.dlx)"
    participant DLQ as "Quarantine Queue (wire.settlement.dlq)"
    participant Worker as "Celery Worker"
    participant DB as "PostgreSQL 16"

    Note over Malicious,DB: Path 5: Poison Pill Quarantine
    Malicious->>API: POST /api/v1/wires (Malformed payload bypassing validation)
    API->>Broker: Publish to wire.settlement.critical
    Broker->>Worker: Basic.Deliver (corrupt_task)
    Worker->>Worker: Execute task -> Fatal Domain Exception (Invalid SWIFT BIC format)
    Worker->>Worker: Detect unrecoverable poison pill (non-retryable)
    Worker->>DB: UPDATE wire_transfers SET status='dead_lettered', failure_reason=...
    Worker->>Broker: Basic.Reject (requeue=False)
    Broker->>DLX: Route rejected message to wire.dlx
    DLX->>DLQ: Bind to wire.settlement.dlq with x-death headers
    Note over DLQ: Message quarantined with headers:<br/>x-death: [{reason: 'rejected', queue: 'wire.settlement.critical'}]
    Note over Worker,DLQ: Critical Queue Remains Unblocked! Workers Continue Normal Processing!
```
