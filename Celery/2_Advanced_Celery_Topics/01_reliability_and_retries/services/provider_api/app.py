from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="Unreliable Provider Simulator")


class ProviderTransactionCreate(BaseModel):
    amount: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    failure_mode: str = "success"

    model_config = ConfigDict(extra="forbid")


class ProviderTransaction(BaseModel):
    provider_transaction_id: str
    idempotency_key: str
    amount: int
    currency: str
    status: str


transactions: dict[str, ProviderTransaction] = {}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/provider/transactions", response_model=ProviderTransaction, status_code=status.HTTP_201_CREATED)
async def create_provider_transaction(
    payload: ProviderTransactionCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1),
):
    existing = transactions.get(idempotency_key)
    if existing:
        return existing

    mode = payload.failure_mode.lower()
    if mode == "permanent":
        raise HTTPException(status_code=400, detail="permanent provider rejection")
    if mode == "temporary":
        raise HTTPException(status_code=503, detail="temporary provider failure")
    if mode == "disconnect":
        raise HTTPException(status_code=503, detail="simulated provider disconnect")

    transaction = ProviderTransaction(
        provider_transaction_id=f"provider-{uuid4()}",
        idempotency_key=idempotency_key,
        amount=payload.amount,
        currency=payload.currency.upper(),
        status="succeeded",
    )
    transactions[idempotency_key] = transaction
    return transaction


@app.get("/provider/transactions/{provider_transaction_id}", response_model=ProviderTransaction)
async def get_provider_transaction(provider_transaction_id: str):
    for transaction in transactions.values():
        if transaction.provider_transaction_id == provider_transaction_id:
            return transaction
    raise HTTPException(status_code=404, detail="provider transaction not found")
