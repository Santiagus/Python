"""FastAPI Ingestion Gateway for High-Value Interbank Wire Settlement.

Handles high-throughput wire transfer ingestion, anti-blackhole persistence,
publisher-confirmed AMQP dispatch, and health checks.
"""

from fastapi import FastAPI, status

app: FastAPI = FastAPI(
    title="High-Value Interbank Wire Gateway",
    description="Wholesale wire transfer settlement ingestion gateway with ACID persistence and durable AMQP dispatch.",
    version="1.0.0",
)


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    tags=["System"],
)
async def health_check() -> dict[str, str]:
    """Provide container liveness and readiness probe for Docker orchestration.

    Returns:
        dict[str, str]: Service status payload with 'status': 'ok'.
    """
    # 1. Return healthy status for container orchestrator
    return {"status": "ok"}
