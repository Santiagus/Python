"""FastAPI application factory for Module 02 Financial Document Underwriting."""

from fastapi import FastAPI
from .config import settings
from .routes import router


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application instance."""
    app = FastAPI(
        title="Financial Document & KYC Underwriting API",
        version="1.0.0",
        description="Ingestion API and Celery Canvas orchestrator for commercial credit underwriting.",
    )

    # Mount API routers
    app.include_router(router, prefix=settings.api_prefix)

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        """Liveness check endpoint."""
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()

