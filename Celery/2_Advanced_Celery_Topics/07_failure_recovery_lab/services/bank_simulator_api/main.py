"""Wholesale Bank Simulator API service.

Emulates external wholesale wire rails (Fedwire / SWIFT MT103 / ISO 20022 pacs.008)
with idempotent transaction tracking, health monitoring, and chaos injection hooks.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status

from shared.schemas import BankDisburseRequest, BankDisburseResponse

app: FastAPI = FastAPI(
    title="Wholesale Bank Simulator API",
    description="Simulates external clearinghouse Fedwire/SWIFT rails with idempotent settlement tracking.",
    version="1.0.0",
)

# 1. In-memory thread-safe store for idempotent clearing transactions
_SETTLED_WIRES: dict[str, dict[str, Any]] = {}


def clear_simulator_store() -> None:
    """Clear all stored wire settlement transactions.

    Used by automated test harnesses and chaos recovery scenarios.
    """
    _SETTLED_WIRES.clear()


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    tags=["System"],
)
async def health_check() -> dict[str, str]:
    """Provide container liveness probe for Docker orchestration.

    Returns:
        dict[str, str]: Service status payload with 'status': 'ok'.
    """
    return {"status": "ok"}


@app.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness Check",
    tags=["System"],
)
async def readiness_check() -> dict[str, str]:
    """Provide container readiness probe for Docker orchestration.

    Returns:
        dict[str, str]: Service status payload with 'status': 'ready'.
    """
    return {"status": "ready"}


@app.post(
    "/v1/chaos/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset Simulator State",
    tags=["Chaos"],
)
async def reset_simulator() -> dict[str, str]:
    """Reset the bank simulator in-memory ledger store.

    Returns:
        dict[str, str]: Confirmation message.
    """
    clear_simulator_store()
    return {"status": "cleared"}


@app.get(
    "/v1/wires/{idempotency_key}",
    response_model=BankDisburseResponse,
    status_code=status.HTTP_200_OK,
    summary="Phase 1: Query Wire Settlement by Idempotency Key",
    tags=["Settlement"],
)
@app.get(
    "/api/v1/fedwire/disburse/{idempotency_key}",
    response_model=BankDisburseResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def query_wire_settlement(idempotency_key: str) -> BankDisburseResponse:
    """Query external clearinghouse state for an existing settlement record.

    Part of the Two-Phase Provider Inquiry pattern. Returns 200 OK if the wire
    has already been settled, or 404 NOT FOUND if never received by the bank.

    Args:
        idempotency_key: Unique client-provided wire idempotency key.

    Returns:
        BankDisburseResponse: Confirmed settlement record.

    Raises:
        HTTPException: 404 NOT FOUND if wire record does not exist.
    """
    record = _SETTLED_WIRES.get(idempotency_key)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wire with idempotency key '{idempotency_key}' not found",
        )
    return BankDisburseResponse.model_validate(record)


@app.post(
    "/v1/wires/settle",
    response_model=BankDisburseResponse,
    status_code=status.HTTP_200_OK,
    summary="Phase 2: Execute Idempotent Wire Disbursement",
    tags=["Settlement"],
)
@app.post(
    "/api/v1/fedwire/disburse",
    response_model=BankDisburseResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def settle_wire_transfer(
    payload: BankDisburseRequest,
    x_simulate_outage: bool | None = Header(default=None, alias="X-Simulate-Outage"),
    simulate_failure: bool = False,
) -> BankDisburseResponse:
    """Execute idempotent settlement disbursement on Fedwire / SWIFT rails.

    If the idempotency key was previously processed, returns the existing confirmation
    record without re-executing funds movement.

    Args:
        payload: Settlement request payload.
        x_simulate_outage: Optional header simulating bank clearinghouse 503 outage.
        simulate_failure: Optional query param simulating bank clearinghouse 503 outage.

    Returns:
        BankDisburseResponse: Settlement confirmation with bank reference id.

    Raises:
        HTTPException: 503 Service Unavailable if chaos mode is active.
    """
    # 1. Chaos injection hook: simulate transient clearinghouse outage
    if x_simulate_outage or simulate_failure:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Simulated wholesale clearinghouse outage",
            headers={"Retry-After": "5"},
        )

    # 2. Check for idempotent cached settlement
    existing = _SETTLED_WIRES.get(payload.idempotency_key)
    if existing is not None:
        return BankDisburseResponse.model_validate(existing)

    # 3. Disburse new wire transfer and generate unique clearing reference
    bank_reference_id = f"FED-WIRE-{uuid.uuid4().hex[:8].upper()}"
    settled_record = {
        "status": "CONFIRMED",
        "bank_reference_id": bank_reference_id,
        "idempotency_key": payload.idempotency_key,
        "amount_cents": payload.amount_cents,
        "currency": payload.currency,
        "settled_at": datetime.now(timezone.utc),
    }

    _SETTLED_WIRES[payload.idempotency_key] = settled_record
    return BankDisburseResponse.model_validate(settled_record)
