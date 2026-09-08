from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountCreate(BaseModel):
    external_reference: str = Field(min_length=1, max_length=255)
    balance: int = Field(default=0, ge=0)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("currency must contain three letters")
        return value


class AccountResponse(AccountCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime


class TransactionCreate(BaseModel):
    account_id: UUID
    amount: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("currency must contain three letters")
        return value


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    idempotency_key: str
    provider_transaction_id: str | None
    amount: int
    currency: str
    status: str
    provider_status: str | None
    sync_attempts: int
    last_synced_at: datetime | None
    next_retry_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
