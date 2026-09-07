# Celery: Major Topics and Practice Projects

The sibling project in `1_First_Steps_with_Celery/` demonstrates the basic
Celery request path: publishing a task, consuming it with a worker, and
returning a result through RabbitMQ. This folder develops the reliability,
scaling, and operational judgment expected from a professional Celery
engineer.

## Major Topics Still Worth Learning

### 1. Reliability and retries

- `self.retry`, `autoretry_for`, retry limits, and exponential backoff
- Acknowledgements, redelivery, `acks_late`, and visibility timeouts
- Idempotent tasks and avoiding duplicate side effects
- Handling transient broker, network, and service failures

### 2. Task workflows

- `chain` for sequential tasks
- `group` for parallel tasks
- `chord` for a callback after a group completes
- Workflow error callbacks and partial failures

### 3. Queues, routing, and worker capacity

- Named queues and task routing
- Worker concurrency and pool choices
- Prefetch settings and fair task distribution
- Priorities, rate limits, and soft or hard time limits

### 4. Scheduling

- Celery Beat and periodic tasks
- Time zones and scheduling accuracy
- Preventing duplicate scheduled work when multiple instances run

### 5. Serialization and application boundaries

- JSON-safe task arguments and return values
- Why database sessions, request objects, and other live resources should not
  be passed to workers
- Keeping tasks small, observable, and safe to run more than once

### 6. Monitoring and operations

- Worker inspection and Flower
- Structured logging, task IDs, and correlation IDs
- Result expiration and backend cleanup
- Dead-letter queues and failed-task recovery
- Graceful worker shutdown and deployment patterns

### 7. Broker and result-backend design

- RabbitMQ versus Redis tradeoffs
- Durable queues, persistent messages, and delivery guarantees
- Choosing when results are needed and when `result_backend = None` is better
- Connection retries, heartbeats, and broker outage behavior

## Learning Path

Build the focused modules in order, then complete the capstone:

1. [Reliability and retries](01_reliability_and_retries/README.md)
2. [Workflows](02_workflows/README.md)
3. [Routing and capacity](03_routing_and_capacity/README.md)
4. [Scheduling](04_scheduling/README.md)
5. [Application integration](05_application_integration/README.md)
6. [Observability and operations](06_observability_and_operations/README.md)
7. [Failure and recovery lab](07_failure_recovery_lab/README.md)
8. [Capstone job platform](08_capstone_job_platform/README.md)

The first seven projects isolate individual skills. The capstone must combine
them into one system so you can demonstrate both detailed knowledge and sound
architecture decisions.

## Professional Completion Standard

For every project, demonstrate:

1. The normal success path and at least one dependency or worker failure.
2. Unit, integration, and end-to-end tests appropriate to the risk.
3. The task's retry, acknowledgement, redelivery, and duplicate-execution
   behavior.
4. A stated delivery guarantee and an idempotency strategy.
5. Measurements for latency, throughput, retries, failures, and queue depth.
6. Reproducible setup with pinned dependencies and environment-based secrets.
7. Documentation explaining operational tradeoffs and recovery procedures.

## CV Guidance

Completing tutorials alone does not establish expert-level experience. A
credible CV claim should be supported by the capstone repository, test reports,
load-test results, architecture decisions, and a failure-injection demo.

Accurate progression examples:

- Early stage: `Built and tested asynchronous Python tasks with Celery and RabbitMQ.`
- Project stage: `Implemented reliable Celery workflows with retries, idempotency,
  routing, scheduling, and integration tests.`
- Strong portfolio stage: `Designed and operated a containerized Celery/RabbitMQ
  job platform with queue isolation, failure recovery, observability, and
  measured throughput.`

Use `Celery expert` only when you can defend production-scale decisions,
incident behavior, performance limits, and tradeoffs in a technical interview.