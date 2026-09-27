"""Standalone Sanctions Watchlist Simulator API.

Provides real-time sanctions and PEP (Politically Exposed Persons) screening
against OFAC, EU, and international watchlists with configurable latency and
error injection for chaos engineering and SRE runbook drills.
"""

import asyncio
from typing import Literal

from fastapi import FastAPI, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

# ==============================================================================
# Prometheus Telemetry Metrics
# ==============================================================================
SANCTIONS_REQUESTS_TOTAL = Counter(
    "sanctions_api_requests_total",
    "Total requests received by the Sanctions API Simulator",
    ["endpoint", "status"],
)
SANCTIONS_REQUEST_DURATION_SECONDS = Histogram(
    "sanctions_api_duration_seconds",
    "Request duration for sanctions screening calls in seconds",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

# ==============================================================================
# In-Memory Watchlist Database
# ==============================================================================
_SANCTIONED_ENTITIES: dict[str, tuple[str, float]] = {
    "VLADIMIR ROSTOV": ("OFAC_SDN", 99.20),
    "SERGEY IVANOV": ("EU_SANCTIONS", 96.50),
    "CARLOS MENDEZ": ("PEP", 92.00),
    "ALPHA HOLDINGS LTD": ("OFAC_SDN", 98.00),
    "PETRO TRANS LLC": ("EU_SANCTIONS", 95.00),
}


# ==============================================================================
# Simulation State Configuration
# ==============================================================================
class SimulationState:
    """Manages mutable simulation configuration for SRE chaos drills."""

    def __init__(self) -> None:
        """Initialize the simulator state with normal operating defaults."""
        self.mode: Literal["normal", "timeout", "error"] = "normal"
        self.latency_seconds: float = 0.0

    def reset(self) -> None:
        """Reset the simulator back to normal zero-fault execution."""
        self.mode = "normal"
        self.latency_seconds = 0.0


_simulation_state = SimulationState()


# ==============================================================================
# Pydantic Schemas
# ==============================================================================
class WatchlistCheckRequest(BaseModel):
    """Payload for screening an individual or corporate entity."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {"entity_name": "Vladimir Rostov"},
                {"entity_name": "Acme Commercial Corp"},
            ]
        },
    )

    entity_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Legal individual or corporate entity to screen against watchlists.",
        examples=["Vladimir Rostov"],
    )


class WatchlistMatch(BaseModel):
    """Details of a single matched entity from a compliance database."""

    model_config = ConfigDict(from_attributes=True)

    entity_name: str = Field(
        ..., description="Matched legal entity name in the sanctions database."
    )
    watchlist_type: str = Field(
        ..., description="Watchlist classification (OFAC_SDN, EU_SANCTIONS, PEP)."
    )
    match_confidence: float = Field(
        ..., ge=0.0, le=100.0, description="Match confidence percentage."
    )


class WatchlistCheckResponse(BaseModel):
    """Screening result envelope returned to calling clients and workers."""

    model_config = ConfigDict(from_attributes=True)

    entity_name: str = Field(..., description="Entity name requested for screening.")
    matches: list[WatchlistMatch] = Field(
        default_factory=list, description="List of matched entities."
    )
    is_sanctioned: bool = Field(
        ..., description="Flag indicating if the entity was positively matched."
    )


class SimulationModeRequest(BaseModel):
    """Payload to alter the simulator's operational degradation behavior."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"mode": "timeout", "latency_seconds": 2.5},
                {"mode": "error", "latency_seconds": 0.0},
                {"mode": "normal", "latency_seconds": 0.0},
            ]
        }
    )

    mode: Literal["normal", "timeout", "error"] = Field(
        default="normal",
        description="Simulation behavior: 'normal', 'timeout' (HTTP 504), or 'error' (HTTP 500).",
    )
    latency_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
        description="Artificial sleep latency injected before returning responses.",
    )


# ==============================================================================
# FastAPI Application Entry Point
# ==============================================================================
app = FastAPI(
    title="Sanctions Watchlist Simulator API",
    description="Compliance simulator for OFAC/EU sanctions matching and chaos injection.",
    version="1.0.0",
)


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """Lightweight health check endpoint for container orchestrators.

    Returns:
        dict[str, str]: Service status payload.
    """
    return {"status": "ok", "service": "sanctions_api"}


@app.get("/metrics", tags=["Observability"])
async def prometheus_metrics() -> Response:
    """Expose Prometheus formatted metrics for telemetry scrapers.

    Returns:
        Response: Plain text response containing exposition-format metrics.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post(
    "/api/v1/watchlists/check",
    response_model=WatchlistCheckResponse,
    status_code=status.HTTP_200_OK,
    tags=["Compliance"],
)
async def check_watchlist(payload: WatchlistCheckRequest) -> WatchlistCheckResponse:
    """Screen an entity name against sanctions and PEP lists.

    Args:
        payload: Entity name to screen.

    Returns:
        WatchlistCheckResponse: Screening outcome with any positive hits.

    Raises:
        HTTPException: HTTP 504 if mode is 'timeout', or HTTP 500 if mode is 'error'.
    """
    with SANCTIONS_REQUEST_DURATION_SECONDS.labels(endpoint="/api/v1/watchlists/check").time():
        # 1. Apply configured artificial latency
        if _simulation_state.latency_seconds > 0:
            await asyncio.sleep(_simulation_state.latency_seconds)

        # 2. Check for chaos injection error modes
        if _simulation_state.mode == "timeout":
            SANCTIONS_REQUESTS_TOTAL.labels(endpoint="/api/v1/watchlists/check", status="504").inc()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Simulated partner gateway timeout in Sanctions Screening API.",
            )

        if _simulation_state.mode == "error":
            SANCTIONS_REQUESTS_TOTAL.labels(endpoint="/api/v1/watchlists/check", status="500").inc()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Simulated internal upstream error in Sanctions Screening API.",
            )

        # 3. Match normalized entity against internal watchlist records
        normalized_query = payload.entity_name.strip().upper()
        matches: list[WatchlistMatch] = []

        for entity, (wl_type, confidence) in _SANCTIONED_ENTITIES.items():
            if (
                entity == normalized_query
                or entity in normalized_query
                or normalized_query in entity
            ):
                matches.append(
                    WatchlistMatch(
                        entity_name=entity,
                        watchlist_type=wl_type,
                        match_confidence=confidence,
                    )
                )

        SANCTIONS_REQUESTS_TOTAL.labels(endpoint="/api/v1/watchlists/check", status="200").inc()
        return WatchlistCheckResponse(
            entity_name=payload.entity_name,
            matches=matches,
            is_sanctioned=len(matches) > 0,
        )


@app.post("/api/v1/simulate/mode", tags=["Chaos Engineering"])
async def set_simulation_mode(payload: SimulationModeRequest) -> dict[str, str | float]:
    """Configure chaos injection mode for testing circuit breakers and alerts.

    Args:
        payload: Mode and latency settings.

    Returns:
        dict[str, str | float]: Updated simulator configuration.
    """
    _simulation_state.mode = payload.mode
    _simulation_state.latency_seconds = payload.latency_seconds
    return {
        "status": "updated",
        "mode": _simulation_state.mode,
        "latency_seconds": _simulation_state.latency_seconds,
    }


@app.post("/api/v1/simulate/reset", tags=["Chaos Engineering"])
async def reset_simulation_mode() -> dict[str, str]:
    """Reset the simulator to default zero-fault operational mode.

    Returns:
        dict[str, str]: Confirmation message.
    """
    _simulation_state.reset()
    return {"status": "reset", "mode": "normal"}
