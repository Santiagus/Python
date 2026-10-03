"""Wholesale Bank Simulator API service.

Emulates external wholesale wire rails (Fedwire / SWIFT MT103 / ISO 20022 pacs.008)
with idempotent transaction tracking and health monitoring.
"""

from fastapi import FastAPI, status

app: FastAPI = FastAPI(
    title="Wholesale Bank Simulator API",
    description="Simulates external clearinghouse Fedwire/SWIFT rails with idempotent settlement tracking.",
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
