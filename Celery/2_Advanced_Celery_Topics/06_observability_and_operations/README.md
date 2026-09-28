# 06: Observability and Operations

Make the system diagnosable and operable by someone who did not write it.

## Deliverables

- Structured logs containing task ID, correlation ID, queue, duration, and outcome.
- Metrics for throughput, latency, retries, failures, queue depth, and age.
- Flower or an equivalent operational dashboard.
- Result expiration, log retention, health checks, and graceful shutdown.
- A runbook for stuck, failed, and overloaded workers.

## Evidence

Create an incident walkthrough showing how one failed task is found from an alert to its root cause.

---

## Project Definition: Real-Time Fraud Detection & AML Sanctions Screening Rail

> **Domain**: Real-Time Fraud Detection & AML Sanctions Screening Rail
> **Industry Reference**: Unit21, Sardine, Stripe Radar, Socure, Chainalysis

This project turns the initial operational requirements above into an observable distributed screening system. The sections below specify its architecture, telemetry, operational controls, and incident evidence.

### Deliverables & Evidence Compliance Matrix

| Original Deliverable / Requirement | Implementation in this System | Verification Test Suite | Compliance Status |
| :--- | :--- | :--- | :---: |
| **1. Structured logs** | JSON logs carry task ID, correlation/request ID, queue, duration, risk score, and outcome; context propagates through API requests (`app/middlewares/correlation.py`) and Celery task headers (`app/dispatcher.py`). Worker tasks log structured fields (`services/worker/tasks/`). | `tests/integration/test_middlewares.py`<br>`tests/unit/test_scoring.py`<br>`tests/unit/test_screening_persistence.py` | **100% Verified** |
| **2. Metrics** | Prometheus exposes request/task throughput, latency percentiles, in-flight tasks, retries, failures, queue depth, and message age; exposed via `GET /metrics` in `app/main.py` and Celery worker signals in `services/worker/celery_app.py`. | `tests/integration/test_metrics_endpoint.py`<br>`tests/unit/test_topology.py` | **100% Verified** |
| **3. Operational dashboard** | Unified Grafana dashboard (`:3000`) and Celery Flower console (`:5555`) provide real-time throughput, latency percentiles, queue lag, and Loki-powered searchable log streams. | `docker-compose.yml` / `docs/ARCHITECTURE_AND_STANDARDS.md` (§4) | **100% Verified** |
| **4. Operational hygiene** | Result expiration (`result_expires=3600`) limits Redis growth; dual health probes cover liveness and dependencies (`/health/live`, `/health/ready`); graceful shutdown handles worker termination (`SIGTERM` client cleanup). | `tests/unit/test_topology.py`<br>`tests/integration/test_health_probes.py`<br>`tests/unit/test_worker_lifecycle.py` | **100% Verified** |
| **5. Worker runbook** | SRE runbooks cover stuck workers and lock deadlocks, queue lag and backpressure, and poison pills, retry storms, and DLQ remediation. Includes inspection & replay CLI scripts. | `tests/unit/test_dlq_tools.py` (6 tests)<br>`docs/ARCHITECTURE_AND_STANDARDS.md` (§5) | **100% Verified** |
| **6. Incident evidence** | A reproducible incident walkthrough follows alert detection through Flower, metrics, trace/log correlation, mitigation, recovery, and data-loss verification (`scripts/incident_walkthrough.py`). | `tests/unit/test_incident_walkthrough.py` (3 tests) | **100% Verified** |

---

## 1. Executive Summary & Problem Statement

In modern financial payment platforms, every transaction authorization requires instantaneous, automated risk evaluation and regulatory compliance screening before funds are cleared or moved:
1. **Real-Time Fraud Scoring**: Evaluating transaction velocity, device IP reputation, cardholder velocity, and high-frequency behavioral anomaly checks under strict latency constraints ($P_{99} \le 120\text{ ms}$).
2. **Anti-Money Laundering (AML) & Sanctions Screening**: Checking counterparties against global sanctions lists (OFAC SDN, PEP, HM Treasury) and high-risk jurisdiction blacklists.
3. **Operational Mission**: Financial platforms cannot treat risk screening as a "black box." When external sanction watchlists degrade, network latency spikes, or worker queues back up, the system must remain diagnosable and operable by on-call site reliability engineers (SREs) who did not write the code.

This project implements an end-to-end observable distributed architecture combining FastAPI, Celery, RabbitMQ, PostgreSQL, Redis, Prometheus, Grafana, Loki, Promtail, OpenTelemetry, and Flower.

---

## 2. Core Operational Deliverables

1. **Structured Contextual Logging**:
   - Machine-parseable JSON logs containing `task_id`, correlation `request_id`, queue name, execution `duration_ms`, risk score, and terminal `outcome`.
   - ContextVar propagation across asynchronous API endpoints and Celery AMQP task headers.
2. **Prometheus Metrics Engine (`/metrics`)**:
   - Real-time scrapable telemetry exposing throughput (requests/sec, tasks/sec), latency histograms ($P_{50}, P_{95}, P_{99}$), task in-flight gauges, failure counters, and queue message age.
3. **Queue Health & Backpressure Telemetry**:
   - Live queue depth and message age tracking across tiered queues (`fraud.screening.critical` vs `fraud.aml.bulk`) with automated SLA breach detection.
4. **Operational Dashboards & Visual Log Search**:
   - Grafana unified operations console (`:3000`) auto-provisioned with Prometheus metrics and Loki searchable log streams.
   - Celery Flower operational console (`:5555`) providing real-time worker introspection, active pools, broker queue depths, and task lifecycle tracking.
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
* **Milestone 1**: Proposal, Architectural Specification, Sequence Diagrams & Test Plan (Completed).
* **Milestone 2**: Infrastructure, Multi-Container Orchestration & Database DDL Schema.
* **Milestone 3**: Domain Models, AMQP Topology, Sanctions Simulator API & Worker Consumer.
* **Milestone 4**: FastAPI Ingestion Gateway, Middlewares, Producer Dispatcher & REST Client Suite.
* **Milestone 5**: Observability Engine (Prometheus Metrics, Flower, Runbooks & Incident Walkthrough).
* **Milestone 6**: Distributed Live E2E Verification & Capacity Contention Benchmarks (Completed).

---

## 5. Operational Quickstart & Interactive Testing Guide

Follow this guide to spin up the entire distributed stack, trigger screening transactions using `requests/requests.rest`, and observe real-time metrics and searchable logs in Grafana.

### Step 1: Boot the Entire Multi-Service Stack
From the project root directory, launch all services via Docker Compose:
```bash
docker compose up --build -d
```

Verify all containers reach a healthy state:
```bash
docker compose ps
```

### Step 2: Access Operations Dashboards & Service Ports

| Service | Host URL | Description | Default Credentials |
| :--- | :--- | :--- | :--- |
| **Grafana Dashboard** | [`http://localhost:3000`](http://localhost:3000) | **Primary Pane**: Real-time throughput, latency percentiles, queue lag, and Loki-powered searchable logs. | Anonymous Admin (No login required) |
| **FastAPI Gateway Swagger** | [`http://localhost:8010/docs`](http://localhost:8010/docs) | Interactive API documentation for transaction ingestion and screening queries. | N/A |
| **Celery Flower Console** | [`http://localhost:5558`](http://localhost:5558) | Worker process inspection, active child pools, task revocations, and queue depths. | N/A |
| **Prometheus Scraper** | [`http://localhost:9095`](http://localhost:9095) | Raw Prometheus telemetry scraper querying `/metrics`. | N/A |
| **Sanctions Simulator** | [`http://localhost:8015/docs`](http://localhost:8015/docs) | External watchlist partner API simulator (OFAC, PEP, timeout injection). | N/A |
| **RabbitMQ Management** | [`http://localhost:15678`](http://localhost:15678) | AMQP exchanges, dead-letter bindings (`fraud.dlx`), and message rates. | `guest` / `guest` |

### Step 3: Trigger Interactive Workflows via REST Client (`requests/requests.rest`)
Open [`requests/requests.rest`](file:///home/sabad/Python/Celery/2_Advanced_Celery_Topics/06_observability_and_operations/requests/requests.rest) in VS Code (with the REST Client extension) and execute the test workflows:

1. **System Health Probes** (`§1`):
   - Click `Send Request` on `GET {{baseUrl}}/health/ready` to verify PostgreSQL, Redis, and RabbitMQ connections.
2. **Happy Path Screening** (`§2`):
   - Click `Send Request` on `POST {{baseUrl}}/api/v1/screenings` to ingest a standard transaction ($250.00).
   - Ingest returns `HTTP 202 Accepted` with `status="processing"`.
   - Execute `Step B` immediately to observe FinTech in-flight visibility (`HTTP 200 OK`, `status="processing"`).
   - Execute `Step C` to inspect terminal approval (`status="approved"`, `risk_score <= 15`).
3. **Sanctions Watchlist Positive Match** (`§3`):
   - Ingest entity `"Vladimir Rostov"` to trigger OFAC sanctions screening.
   - Inspect terminal decision (`status="blocked"`, `risk_score >= 95`).
4. **Partner Degradation & Result Envelope Fallback** (`§4`):
   - Inject 2.5s latency into the sanctions simulator: `POST {{sanctionsUrl}}/api/v1/simulate/mode`.
   - Ingest a transaction; observe non-fatal timeout handled gracefully via Result Envelope (`status="flagged_review"`).
   - Reset the simulator back to normal: `POST {{sanctionsUrl}}/api/v1/simulate/reset`.
5. **Atomic Idempotency Verification** (`§5`):
   - Send duplicate transactions with the same `transaction_id`; observe the second request safely returning `HTTP 200 OK` with the existing record.

### Step 4: Monitor Telemetry & Search Logs in Grafana
Navigate to [`http://localhost:3000`](http://localhost:3000) and open the **Fraud Screening & AML Observability** dashboard:

1. **Observe Real-Time Metrics**:
   - Ingestion RPS and Celery Task Throughput counters rise dynamically with your requests.
   - Latency Percentiles ($P_{50}, P_{95}, P_{99}$) reflect API and Celery execution times.
   - Queue Depth and Message Age reflect RabbitMQ backpressure.
2. **Search Logs in Real Time (Loki)**:
   - Scroll down to the **Live Searchable Structured Logs** panel.
   - In the **Log Search** textbox at the top of the dashboard, enter your `request_id` (e.g. `req-audit-...`) or `status="blocked"` to filter across both API and Celery worker streams simultaneously.
   - Click any log line to unpack JSON fields (`risk_score`, `decision_reason`, `duration_ms`).

### Step 5: Clean Teardown
When finished, cleanly shut down all services and tear down test volumes:
```bash
docker compose down -v
```
