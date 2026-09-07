# 05: Application Integration

Build an API that submits background jobs and reports their status asynchronously.

## Deliverables

- Submission, status, retry, and cancellation endpoints.
- Authentication and input validation at the API boundary.
- No blocking `result.get()` calls in request handlers.
- Stable task-state and error responses for clients.
- Contract tests between the API and Celery tasks.

## Evidence

Document API latency separately from job latency and explain how clients handle eventual completion.
