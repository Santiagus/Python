# 08: Capstone Job Platform

Combine the earlier modules into a production-style background job platform.

## Required capabilities

- API submission and asynchronous status tracking.
- Idempotent tasks with bounded retries and backoff.
- A workflow using sequential and parallel stages.
- Queue routing for critical and bulk workloads.
- Scheduled cleanup or reporting.
- Structured logs, metrics, dashboard, health checks, and a runbook.
- RabbitMQ, separate worker processes, and containerized local deployment.

## Professional acceptance criteria

- Unit, integration, end-to-end, contract, and failure-injection tests.
- A documented delivery and retry guarantee for every task.
- Reproducible setup with pinned dependencies and environment configuration.
- Load-test results with stated throughput and latency limits.
- No secrets in source control and no unsafe live objects passed to tasks.
- A concise architecture decision record explaining broker, backend, queue, and worker choices.

## Portfolio evidence

Publish an architecture diagram, test report, load-test summary, incident runbook,
and a short demo showing recovery after worker and broker failures.
