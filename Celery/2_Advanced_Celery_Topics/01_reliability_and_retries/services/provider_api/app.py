"""Fault-injection provider API used to simulate retryable and permanent external failures."""

import logging
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="Unreliable Provider Simulator")
logger = logging.getLogger(__name__)


class ProviderTransactionCreate(BaseModel):
    """Provider request payload with a configurable failure mode."""

    amount: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    failure_mode: str = "sequence"

    model_config = ConfigDict(extra="forbid")


class ProviderTransaction(BaseModel):
    """Successful provider result or replayed response payload."""

    provider_transaction_id: str
    idempotency_key: str
    amount: int
    currency: str
    status: str


transactions: dict[str, ProviderTransaction] = {}
attempts: dict[str, int] = {}


@app.get("/health")
async def health() -> dict[str, str]:
    """Return the provider health status."""
    return {"status": "ok"}


@app.post("/provider/transactions", response_model=ProviderTransaction, status_code=status.HTTP_201_CREATED)
async def create_provider_transaction(
    payload: ProviderTransactionCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1),
):
    """Create or replay a provider transaction while deliberately failing based on mode."""
    mode = payload.failure_mode.lower()
    existing = transactions.get(idempotency_key)
    if existing:
        # Idempotency is checked before fault injection so retries replay the
        # accepted provider transaction rather than creating another one.
        logger.info(
            "provider_transaction_replayed idempotency_key=%s provider_transaction_id=%s status=%s",
            idempotency_key,
            existing.provider_transaction_id,
            existing.status,
            extra={
                "idempotency_key": idempotency_key,
                "provider_transaction_id": existing.provider_transaction_id,
                "status": existing.status,
            },
        )
        return existing

    attempt_number = attempts.get(idempotency_key, 0) + 1
    attempts[idempotency_key] = attempt_number
    logger.info(
        "provider_transaction_attempt idempotency_key=%s attempt=%s failure_mode=%s",
        idempotency_key,
        attempt_number,
        mode,
        extra={
            "idempotency_key": idempotency_key,
            "attempt_number": attempt_number,
            "failure_mode": mode,
        },
    )

    # Fault modes are deterministic by design, making retry behavior reproducible
    # in tests and easy to inspect during local development.
    if mode in {"sequence", "temporary"} and attempt_number <= 2:
        logger.warning(
            "provider_transaction_temporary_failure idempotency_key=%s attempt=%s",
            idempotency_key,
            attempt_number,
            extra={"idempotency_key": idempotency_key, "attempt_number": attempt_number},
        )
        raise HTTPException(status_code=503, detail="temporary provider failure")
    if mode == "permanent":
        logger.warning(
            "provider_transaction_permanent_failure idempotency_key=%s attempt=%s",
            idempotency_key,
            attempt_number,
            extra={"idempotency_key": idempotency_key, "attempt_number": attempt_number},
        )
        raise HTTPException(status_code=400, detail="permanent provider rejection")
    if mode == "disconnect":
        logger.warning(
            "provider_transaction_disconnect idempotency_key=%s attempt=%s",
            idempotency_key,
            attempt_number,
            extra={"idempotency_key": idempotency_key, "attempt_number": attempt_number},
        )
        raise HTTPException(status_code=503, detail="simulated provider disconnect")

    transaction = ProviderTransaction(
        provider_transaction_id=f"provider-{uuid4()}",
        idempotency_key=idempotency_key,
        amount=payload.amount,
        currency=payload.currency.upper(),
        status="succeeded",
    )
    transactions[idempotency_key] = transaction
    logger.info(
        "provider_transaction_succeeded idempotency_key=%s attempt=%s provider_transaction_id=%s",
        idempotency_key,
        attempt_number,
        transaction.provider_transaction_id,
        extra={
            "idempotency_key": idempotency_key,
            "attempt_number": attempt_number,
            "provider_transaction_id": transaction.provider_transaction_id,
            "status": transaction.status,
        },
    )
    return transaction


@app.get("/provider/transactions/{provider_transaction_id}", response_model=ProviderTransaction)
async def get_provider_transaction(provider_transaction_id: str):
    """Look up a stored provider transaction by its provider id."""
    for transaction in transactions.values():
        if transaction.provider_transaction_id == provider_transaction_id:
            logger.info(
                "provider_transaction_lookup_succeeded provider_transaction_id=%s",
                provider_transaction_id,
                extra={"provider_transaction_id": provider_transaction_id},
            )
            return transaction
    logger.warning(
        "provider_transaction_lookup_not_found provider_transaction_id=%s",
        provider_transaction_id,
        extra={"provider_transaction_id": provider_transaction_id},
    )
    raise HTTPException(status_code=404, detail="provider transaction not found")
