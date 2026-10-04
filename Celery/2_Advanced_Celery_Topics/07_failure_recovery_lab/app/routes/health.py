"""Health and readiness probe routes for container orchestrators and load balancers."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.wires import get_db_session

router: APIRouter = APIRouter(tags=["System"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
)
async def health_check() -> dict[str, str]:
    """Provide container liveness probe for Docker orchestration.

    Returns:
        dict[str, str]: Liveness status dictionary.
    """
    # 1. Return immediate healthy confirmation
    return {"status": "ok"}


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness Probe",
)
async def readiness_check(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Provide container readiness probe verifying database connectivity.

    Args:
        session: Injected asynchronous database session.

    Returns:
        dict[str, Any]: Readiness status dictionary.

    Raises:
        HTTPException: If database connectivity cannot be verified.
    """
    try:
        # 1. Execute lightweight database ping
        await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        # 2. Raise 503 Service Unavailable if ping fails
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unreachable: {exc}",
        ) from exc
