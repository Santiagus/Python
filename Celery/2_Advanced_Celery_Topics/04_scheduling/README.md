# 04: Scheduling

Build a scheduled reporting and cleanup service with Celery Beat.

## Deliverables

- Periodic tasks with explicit timezone behavior.
- Idempotent report generation for each reporting period.
- A lock or durable uniqueness strategy for multiple Beat instances.
- Tests for missed schedules, duplicate delivery, and overlapping runs.

## Evidence

Document the scheduler deployment model and how you detect and recover from missed work.
