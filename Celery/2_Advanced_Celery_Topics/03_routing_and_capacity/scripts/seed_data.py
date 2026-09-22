"""Seed synthetic enterprise accounts and test data into PostgreSQL.

Usage:
    python scripts/seed_data.py
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session_factory
from app.models import Account

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_data")

SEED_ACCOUNTS = [
    {
        "account_id": UUID("a0000000-0000-0000-0000-000000000001"),
        "account_number": "1000112233445501",
        "account_mask": "******5501",
        "balance_cents": 1000000000,  # $10,000,000.00
        "currency": "USD",
    },
    {
        "account_id": UUID("a0000000-0000-0000-0000-000000000002"),
        "account_number": "2000223344556602",
        "account_mask": "******6602",
        "balance_cents": 500000000,  # $5,000,000.00
        "currency": "USD",
    },
    {
        "account_id": UUID("a0000000-0000-0000-0000-000000000003"),
        "account_number": "3000334455667703",
        "account_mask": "******7703",
        "balance_cents": 10000000,  # $100,000.00
        "currency": "USD",
    },
    {
        "account_id": UUID("a0000000-0000-0000-0000-000000000004"),
        "account_number": "4000445566778804",
        "account_mask": "******8804",
        "balance_cents": 5000,  # $50.00 (Depleted)
        "currency": "USD",
    },
]


async def seed_database() -> None:
    """Insert specimen accounts if not already present."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            for acc_data in SEED_ACCOUNTS:
                stmt = select(Account).where(Account.account_id == acc_data["account_id"])
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()
                if not existing:
                    account = Account(**acc_data)
                    session.add(account)
                    logger.info("Created seed account: %s (%s)", acc_data["account_number"], acc_data["account_mask"])
                else:
                    logger.info("Seed account already exists: %s", acc_data["account_number"])


if __name__ == "__main__":
    asyncio.run(seed_database())

