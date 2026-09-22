"""Seed synthetic enterprise accounts and test data into PostgreSQL.

Usage:
    python scripts/seed_data.py
    python scripts/seed_data.py --count 100
    python scripts/seed_data.py --reset --count 100
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import select
# Ensure repository root is on sys.path for direct script execution
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import get_settings
from sqlalchemy import delete, select

from app.db import get_session_factory
from app.models import Account
from app.models import Account, BatchSettlement, Disbursement, Payment

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_data")

SEED_ACCOUNTS = [
# Core specimen accounts with realistic balances and masks
CORE_SEED_ACCOUNTS: list[dict[str, Any]] = [
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
def generate_seed_accounts(total_count: int = 100) -> list[dict[str, Any]]:
    """Generate account definitions up to total_count.

    Preserves core specimen accounts 1..4 and dynamically generates 5..total_count
    to support high-concurrency multi-client benchmarks (e.g., Locust).

    Args:
        total_count: Target number of enterprise accounts.

    Returns:
        list[dict[str, Any]]: List of account record dicts.
    """
    accounts = list(CORE_SEED_ACCOUNTS[:total_count])
    for i in range(len(accounts) + 1, total_count + 1):
        accounts.append({
            "account_id": UUID(f"a0000000-0000-0000-0000-{i:012d}"),
            "account_number": f"1000{i:012d}",
            "account_mask": f"******{str(i)[-4:]:0>4}",
            "balance_cents": 1000000000,  # $10,000,000.00
            "currency": "USD",
        })
    return accounts


async def seed_database(count: int = 100, reset: bool = False) -> None:
    """Insert specimen accounts if not already present.

    Args:
        count: Total number of accounts to seed.
        reset: If True, clears existing tables before seeding.
    """
    session_factory = get_session_factory()
    target_accounts = generate_seed_accounts(count)

    async with session_factory() as session:
        async with session.begin():
            for acc_data in SEED_ACCOUNTS:
            if reset:
                logger.info("Reset requested: purging dependent tables and accounts...")
                await session.execute(delete(Disbursement))
                await session.execute(delete(BatchSettlement))
                await session.execute(delete(Payment))
                await session.execute(delete(Account))
                logger.info("Purged existing transaction and account records.")

            created_count = 0
            existing_count = 0
            for acc_data in target_accounts:
                stmt = select(Account).where(Account.account_id == acc_data["account_id"])
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()
                if not existing:
                    account = Account(**acc_data)
                    session.add(account)
                    logger.info("Created seed account: %s (%s)", acc_data["account_number"], acc_data["account_mask"])
                    created_count += 1
                else:
                    logger.info("Seed account already exists: %s", acc_data["account_number"])
                    existing_count += 1

            logger.info(
                "Database seed complete: %d created, %d already existed (Total target: %d)",
                created_count,
                existing_count,
                count,
            )


def main() -> None:
    """CLI entrypoint with parameter parsing and sensible defaults."""
    parser = argparse.ArgumentParser(
        description="Seed synthetic enterprise accounts and test data into PostgreSQL."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Total number of accounts to ensure seeded (default: 100)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Purge existing tables before seeding (default: False)",
    )
    args = parser.parse_args()

    asyncio.run(seed_database(count=args.count, reset=args.reset))


if __name__ == "__main__":
    asyncio.run(seed_database())
    main()

