"""API route handlers for creating, listing, and querying transaction records."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Database
from .models import Account, Transaction, TransactionStatus
from .schemas import AccountCreate, AccountResponse, TransactionCreate, TransactionResponse
from .tasks import enqueue_transaction_sync

logger = logging.getLogger(__name__)
router = APIRouter()


def get_database() -> Database:
    """Placeholder dependency used by the app factory to inject the database."""
    raise RuntimeError("Database dependency has not been configured")


async def get_session(database: Database = Depends(get_database)):
    """Yield a transactional SQLAlchemy session for each request."""
    async with database.session() as session:
        yield session


@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(payload: AccountCreate, session: AsyncSession = Depends(get_session)):
    """Create a new account and persist it in the database."""
    account = Account(**payload.model_dump())
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="account already exists") from exc
    await session.refresh(account)
    return account


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(session: AsyncSession = Depends(get_session)):
    """Return all accounts ordered by creation time, newest first."""
    result = await session.scalars(select(Account).order_by(Account.created_at.desc()))
    return list(result)


@router.post("/transactions", response_model=TransactionResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_transaction(
    payload: TransactionCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_session),
):
    """Create a pending transaction, enqueue synchronization, and return 202 Accepted."""
    # Reusing an idempotency key returns the original local record and prevents
    # a client retry from creating a second transaction.
    existing = await session.scalar(
        select(Transaction).where(Transaction.idempotency_key == idempotency_key)
    )
    if existing:
        response.headers["Location"] = f"/transactions/{existing.id}"
        return existing

    account = await session.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    if account.currency != payload.currency:
        raise HTTPException(status_code=422, detail="transaction currency must match account currency")

    # Commit the local record before publishing work. If the broker is down,
    # reconciliation can still discover this pending transaction later.
    transaction = Transaction(
        **payload.model_dump(),
        idempotency_key=idempotency_key,
        status=TransactionStatus.PENDING,
    )
    session.add(transaction)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="idempotency key already exists") from exc
    await session.refresh(transaction)
    response.headers["Location"] = f"/transactions/{transaction.id}"
    try:
        # Enqueueing is intentionally best-effort after commit; returning an
        # error here would hide a transaction that is already durable locally.
        enqueue_transaction_sync(str(transaction.id), idempotency_key)
    except Exception:
        logger.warning(
            "transaction_sync_enqueue_failed",
            extra={"transaction_id": str(transaction.id)},
            exc_info=True,
        )
    logger.info("transaction_created", extra={"transaction_id": str(transaction.id)})
    return transaction


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(transaction_id: UUID, session: AsyncSession = Depends(get_session)):
    """Fetch a transaction by id or raise a 404 error if it is missing."""
    transaction = await session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/transactions", response_model=list[TransactionResponse])
async def list_transactions(
    account_id: UUID | None = None,
    transaction_status: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
):
    """List transactions with optional account and status filters."""
    query = select(Transaction).order_by(Transaction.created_at.desc())
    if account_id:
        query = query.where(Transaction.account_id == account_id)
    if transaction_status:
        query = query.where(Transaction.status == transaction_status)
    result = await session.scalars(query)
    return list(result)
