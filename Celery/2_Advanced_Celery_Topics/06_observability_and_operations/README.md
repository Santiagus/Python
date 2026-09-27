# 06: Observability, Distributed Telemetry & Operations

> **Domain**: Real-Time Fraud Detection & AML Sanctions Screening Rail  
> **Industry Reference**: Unit21, Sardine, Stripe Radar, Socure, Chainalysis

---

## 1. Executive Summary & Problem Statement

In modern financial payment platforms, every transaction authorization requires instantaneous, automated risk evaluation and regulatory compliance screening before funds are cleared or moved:
1. **Real-Time Fraud Scoring**: Evaluating transaction velocity, device IP reputation, cardholder velocity, and high-frequency behavioral anomaly checks under strict latency constraints ($P_{99} \le 120\text{ ms}$).
2. **Anti-Money Laundering (AML) & Sanctions Screening**: Checking counterparties against global sanctions lists (OFAC SDN, PEP, HM Treasury) and high-risk jurisdiction blacklists.
3. **Operational Mission**: Financial platforms cannot treat risk screening as a "black box." When external sanction watchlists degrade, network latency spikes, or worker queues back up, the system must remain diagnosable and operable by on-call site reliability engineers (SREs) who did not write the code.

This project implements an end-to-end observable distributed architecture combining FastAPI, Celery, RabbitMQ, PostgreSQL, Redis, Prometheus, OpenTelemetry, and Flower.

---

## 2. Core Operational Deliverables

1. **Structured Contextual Logging**:
   - Machine-parseable JSON logs containing `task_id`, correlation `request_id`, queue name, execution `duration_ms`, risk score, and terminal `outcome`.
   - ContextVar propagation across asynchronous API endpoints and Celery AMQP task headers.
2. **Prometheus Metrics Engine (`/metrics`)**:
   - Real-time scrapable telemetry exposing throughput (requests/sec, tasks/sec), latency histograms ($P_{50}, P_{95}, P_{99}$), task in-flight gauges, failure counters, and queue message age.
3. **Queue Health & Backpressure Telemetry**:
   - Live queue depth and message age tracking across tiered queues (`fraud.screening.critical` vs `fraud.aml.bulk`) with automated SLA breach detection.
4. **Operational Dashboard & Visual Inspection**:
   - Celery Flower operational console providing real-time worker introspection, active pools, broker queue depths, and task lifecycle tracking.
5. **Operational Hygiene & Lifecycle Guarantees**:
   - Result expiration (`result_expires=3600`) to prevent Redis memory bloat.
   - Dual-probe container health checks: `/health/live` (lightweight process event loop ping) and `/health/ready` (eager PostgreSQL, Redis, and RabbitMQ connection pool pings).
   - Graceful worker shutdown handling (`SIGTERM`) ensuring distributed locks are released and connection pools are cleanly closed.
6. **SRE Operational Runbook**:
   - Actionable step-by-step triage runbooks for the three major distributed failure modes:
     - **Runbook A**: Stuck/Hung Worker & Lock Deadlock Triage.
     - **Runbook B**: Queue Lag & Backpressure Saturation (Prefetch tuning & scaling).
     - **Runbook C**: Poison Pill, Retry Storms & Dead Letter Queue (DLQ) Remediation.
7. **Incident Walkthrough & Evidence**:
   - An end-to-end incident post-mortem reproduction script demonstrating:
     - Alert detection (Prometheus latency breach / queue lag alert).
     - Distributed triage (Flower + Prometheus `/metrics`).
     - Root-cause isolation via OpenTelemetry W3C `traceparent` and structured log correlation.
     - Operational mitigation via Celery broadcast commands.
     - Service recovery and zero data loss verification.

---

## 3. High-Level Architectural Highlights

* **Tiered Hybrid Queue Topology**:
  - `fraud.screening.critical`: High-priority real-time velocity and scoring checks ($P_{99} \le 120\text{ ms}$).
  - `fraud.aml.bulk`: Asynchronous, deep AML watchlist and fuzzy graph entity matching.
  - Dedicated dead-letter exchange (`fraud.dlx`) and poison pill quarantine queue (`fraud.screening.dlq`).
* **In-Flight State Visibility & ACID Storage**:
  - Immediate state machine persistence on `HTTP 202 ACCEPTED` (`status="processing"`).
  - Immediate `HTTP 200 OK` on subsequent `GET /api/v1/screenings/{id}` requests (zero 404 race conditions).
  - Minor-unit financial precision (integer cents) stored as `NUMERIC(14, 2)`.
  - Partial B-Tree indexes on active states (`WHERE status IN ('pending', 'processing')`).
* **Circuit-Breaker & Degraded Result Envelopes**:
  - Non-fatal third-party watchlist timeouts degrade gracefully using the **Result Envelope Pattern** (`status="degraded"`), applying local fallback rules and routing to compliance review rather than dropping transactions.

---

## 4. Project Roadmap & Milestone Progression

This project module strictly follows the standard 6-milestone development lifecycle:
* **Milestone 1**: Proposal, Architectural Specification, Sequence Diagrams & Test Plan (Current).
* **Milestone 2**: Infrastructure, Multi-Container Orchestration & Database DDL Schema.
* **Milestone 3**: Domain Models, AMQP Topology, Sanctions Simulator API & Worker Consumer.
* **Milestone 4**: FastAPI Ingestion Gateway, Middlewares, Producer Dispatcher & REST Client Suite.
* **Milestone 5**: Observability Engine (Prometheus Metrics, Flower, Runbooks & Incident Walkthrough).
* **Milestone 6**: Distributed Live E2E Verification & Capacity Contention Benchmarks.
