"""Partner Bank Simulator API: Real-Time Clearing & Batch Settlement Mock.

Simulates external banking rails (FedNow, RTP, ACH) with configurable network latency
and fault injection headers (X-Mock-Delay-Ms, X-Simulate-Failure) for rigorous testing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger("bank_simulator_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="Partner Bank Clearing Simulator API",
    version="1.0.0",
    description="Simulates FedNow, RTP, and ACH partner clearing gateways.",
)


# =============================================================================
# Request & Response Schemas
# =============================================================================

class InstantClearingRequest(BaseModel):
    """Payload for real-time payment clearing."""
    payment_id: str = Field(..., description="Orchestrator payment UUID")
    amount_cents: int = Field(..., gt=0, description="Transaction amount in integer cents")
    rail: str = Field(..., description="Target rail: 'fednow' or 'rtp'")
    destination_account_number: str = Field(..., description="Counterparty account number")
    destination_routing_number: str = Field(..., description="9-digit routing transit number")


class InstantClearingResponse(BaseModel):
    """Response returned upon clearing an instant payment."""
    status: str = Field(..., examples=["settled"])
    clearing_reference: str = Field(..., description="Clearing network transaction identifier")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of settlement")


class BatchChunkItem(BaseModel):
    """Single item in a batch chunk."""
    disbursement_id: str
    account_number: str
    routing_number: str
    amount_cents: int


class BatchChunkRequest(BaseModel):
    """Payload for batch ACH settlement chunk clearing."""
    batch_id: str = Field(..., description="Batch settlement parent UUID")
    chunk_index: int = Field(..., ge=0, description="Zero-indexed chunk sequence number")
    items: list[BatchChunkItem] = Field(..., min_length=1, description="Disbursement items")


class BatchChunkResponse(BaseModel):
    """Response returned upon clearing a batch chunk."""
    status: str = Field(..., examples=["accepted"])
    batch_id: str
    chunk_index: int
    cleared_count: int


# =============================================================================
# Mock Endpoints
# =============================================================================

@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for container probes."""
    return {"status": "healthy", "service": "bank_simulator_api"}


@app.post("/clearing/instant", response_model=InstantClearingResponse)
async def clear_instant_payment(
    payload: InstantClearingRequest,
    x_mock_delay_ms: int | None = Header(default=None, alias="X-Mock-Delay-Ms"),
    x_simulate_failure: str | None = Header(default=None, alias="X-Simulate-Failure"),
) -> InstantClearingResponse:
    """Clear a real-time instant payment via FedNow or RTP.

    Supports fault injection:
    - X-Mock-Delay-Ms: Injects artificial network latency.
    - X-Simulate-Failure: Returns HTTP 502 Bad Gateway to test compensating rollbacks.
    - Routing starting with '999': Deterministic test trigger for partner rejection.
    """
    # 1. Simulate artificial network latency if requested
    if x_mock_delay_ms and x_mock_delay_ms > 0:
        await asyncio.sleep(x_mock_delay_ms / 1000.0)

    # 2. Check for simulated rail failure or invalid test routing
    if (x_simulate_failure and x_simulate_failure.lower() == "true") or payload.destination_routing_number.startswith("999"):
        logger.warning(
            "simulated_bank_rail_rejection",
            extra={"payment_id": payload.payment_id, "rail": payload.rail},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Partner bank rail '{payload.rail}' temporarily unavailable or rejected routing",
        )

    # 3. Generate authoritative clearing confirmation
    rail_tag = payload.rail.upper()
    clearing_ref = f"CLR_{rail_tag}_{uuid4().hex[:12].upper()}"
    settled_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "instant_payment_cleared",
        extra={
            "payment_id": payload.payment_id,
            "rail": payload.rail,
            "clearing_ref": clearing_ref,
            "amount_cents": payload.amount_cents,
        },
    )

    return InstantClearingResponse(
        status="settled",
        clearing_reference=clearing_ref,
        timestamp=settled_at,
    )


@app.post("/clearing/batch-chunk", response_model=BatchChunkResponse)
async def clear_batch_chunk(
    payload: BatchChunkRequest,
    x_mock_delay_ms: int | None = Header(default=None, alias="X-Mock-Delay-Ms"),
) -> BatchChunkResponse:
    """Clear an ACH batch disbursement chunk."""
    # 1. Simulate artificial batch transmission latency
    if x_mock_delay_ms and x_mock_delay_ms > 0:
        await asyncio.sleep(x_mock_delay_ms / 1000.0)

    logger.info(
        "batch_chunk_cleared",
        extra={
            "batch_id": payload.batch_id,
            "chunk_index": payload.chunk_index,
            "item_count": len(payload.items),
        },
    )

    return BatchChunkResponse(
        status="accepted",
        batch_id=payload.batch_id,
        chunk_index=payload.chunk_index,
        cleared_count=len(payload.items),
    )

