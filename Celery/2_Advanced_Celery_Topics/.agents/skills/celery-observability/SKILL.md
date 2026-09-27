---
name: celery-observability
description: >-
  Configure OpenTelemetry distributed tracing, Prometheus metrics (/metrics), dual-probe
  health endpoints (/health/live, /health/ready), and graceful worker shutdown for Celery
  and FastAPI. Use this skill ONLY when observability, telemetry, or production monitoring
  is explicitly requested or required.
---

# Celery & FastAPI Observability, Telemetry & Graceful Lifecycle

This skill guides the implementation of production-grade distributed tracing (OpenTelemetry), application and worker metrics (Prometheus `/metrics`), container health probes, and graceful worker shutdown routines.

---

> [!IMPORTANT]
> **Strict Opt-In Invariant**:
> Observability and telemetry (OpenTelemetry tracing, Prometheus `/metrics` endpoints, latency histograms, and queue gauges) must **ONLY** be added when explicitly required or requested by the user/project specification.
> Standard or basic project modules must remain lean and must NOT be bloated with telemetry libraries or exporters unless requested.

---

## 1. Prometheus Metrics Collection (`/metrics`)

When metrics are required, expose a Prometheus scraping endpoint using `prometheus_client` without blocking the async event loop.

### Core Metrics Registry
```python
"""Observability metrics definitions for HTTP gateway and Celery workers."""

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter, Response

# 1. API Gateway Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests handled by the API gateway.",
    ["method", "endpoint", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# 2. Celery Worker Execution Metrics
CELERY_TASKS_TOTAL = Counter(
    "celery_tasks_total",
    "Total count of Celery tasks executed.",
    ["task_name", "status"],
)
CELERY_TASK_DURATION_SECONDS = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration in seconds.",
    ["task_name"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
CELERY_TASKS_IN_FLIGHT = Gauge(
    "celery_tasks_in_flight",
    "Number of Celery tasks currently executing in this worker child process.",
    ["task_name"],
)

# 3. Router exposing /metrics
metrics_router = APIRouter(tags=["Observability"])

@metrics_router.get("/metrics")
async def get_metrics() -> Response:
    """Scrape Prometheus metrics for application and worker monitoring."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

### Worker Signal Instrumentation
Attach metric hooks to Celery task lifecycle signals:
```python
import time
from celery import signals

_task_start_times: dict[str, float] = {}

@signals.task_prerun.connect
def on_task_prerun(task_id: str, task, **kwargs):
    _task_start_times[task_id] = time.perf_counter()
    CELERY_TASKS_IN_FLIGHT.labels(task_name=task.name).inc()

@signals.task_postrun.connect
def on_task_postrun(task_id: str, task, state: str, **kwargs):
    CELERY_TASKS_IN_FLIGHT.labels(task_name=task.name).dec()
    CELERY_TASKS_TOTAL.labels(task_name=task.name, status=state).inc()
    if start_time := _task_start_times.pop(task_id, None):
        duration = time.perf_counter() - start_time
        CELERY_TASK_DURATION_SECONDS.labels(task_name=task.name).observe(duration)
```

---

## 2. OpenTelemetry Distributed Tracing

Propagate W3C Trace Context (`traceparent`) across the HTTP $\to$ RabbitMQ Broker $\to$ Worker $\to$ External Partner boundary so transactions can be traced end-to-end in Jaeger, Grafana Tempo, or Honeycomb.

### 1. Producer Header Injection
When dispatching a Celery task from the API gateway, serialize the active OpenTelemetry span context into task headers:
```python
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

def dispatch_task_with_trace(task_signature, *args, **kwargs):
    """Dispatch Celery task with injected W3C traceparent headers."""
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    
    # Pass carrier inside Celery headers
    return task_signature.apply_async(
        args=args,
        kwargs=kwargs,
        headers={"traceparent": carrier.get("traceparent", "")},
    )
```

### 2. Worker Header Extraction
In the Celery worker task execution, extract the carrier to parent the worker span:
```python
@signals.task_prerun.connect
def extract_trace_context(task, **kwargs):
    request = getattr(task, "request", None)
    if request and hasattr(request, "headers") and request.headers:
        carrier = {"traceparent": request.headers.get("traceparent", "")}
        ctx = TraceContextTextMapPropagator().extract(carrier)
        trace.set_span_in_context(trace.get_current_span(ctx))
```

---

## 3. Container Health Probes: Liveness vs. Readiness

In containerized or orchestrator deployments (Kubernetes, AWS ECS, Docker Compose), separate health checks into distinct probes:

1. **Liveness Probe (`/health/live`)**:
   - Asserts the Python runtime and event loop are responsive.
   - Does **NOT** test external services (PostgreSQL/Redis); failing an external dependency should not cause the orchestrator to restart a healthy container.
   ```python
   @router.get("/health/live", tags=["Health"])
   async def health_live() -> dict[str, str]:
       return {"status": "ok"}
   ```

2. **Readiness Probe (`/health/ready`)**:
   - Asserts the service can actively accept user traffic.
   - Pings PostgreSQL (`SELECT 1`), Redis (`PING`), and AMQP broker connection pools.
   - Returns `HTTP 503 SERVICE UNAVAILABLE` if downstream dependencies are unreachable, pulling the instance from the ingress balancer.
   ```python
   @router.get("/health/ready", tags=["Health"])
   async def health_ready(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
       # 1. Ping PostgreSQL
       await session.execute(text("SELECT 1"))
       # 2. Ping Redis
       redis_client = get_redis_client()
       await redis_client.ping()
       return {"status": "ready"}
   ```

---

## 4. Graceful Worker Shutdown & Lock Eviction

Prevent stranded Redis distributed locks when workers receive `SIGTERM` during rolling container updates or restarts:

```python
from celery import signals
import logging

logger = logging.getLogger(__name__)

@signals.worker_shutting_down.connect
def on_worker_shutting_down(sig, how, exitcode, **kwargs):
    """Cleanly release active distributed locks and flush connection pools upon SIGTERM."""
    logger.info("worker_shutting_down_signal_received", extra={"signal": sig, "how": how})
    
    # 1. Cleanly release process-local locks if held
    try:
        from services.worker.redis_client import release_held_worker_locks
        release_held_worker_locks()
    except Exception as exc:
        logger.warning("failed_to_release_locks_on_shutdown", extra={"error": str(exc)})
    
    # 2. Dispose of database engine connection pool
    try:
        from services.worker.database import dispose_worker_engine
        dispose_worker_engine()
    except Exception as exc:
        logger.warning("failed_to_dispose_engine_on_shutdown", extra={"error": str(exc)})
```
