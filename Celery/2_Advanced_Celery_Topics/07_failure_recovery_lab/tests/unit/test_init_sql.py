"""Unit tests for PostgreSQL relational database DDL (init.sql).

Verifies financial ledger table definitions, primary keys, check constraints,
foreign key actions, index deduplication invariants, and state-machine partial indexes.
"""

import re
from pathlib import Path


def test_init_sql_file_exists(workspace_root: Path) -> None:
    """Verify init.sql exists in workspace root and is non-empty."""
    init_sql = workspace_root / "init.sql"
    assert init_sql.is_file(), "init.sql must exist at workspace root"
    content = init_sql.read_text(encoding="utf-8").strip()
    assert len(content) > 0, "init.sql must not be empty"


def test_uuid_extension_present(init_sql_content: str) -> None:
    """Verify UUID extension declaration."""
    assert 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";' in init_sql_content


def test_wire_transfers_table_schema(init_sql_content: str) -> None:
    """Verify wire_transfers table columns and idempotency constraints."""
    # 1. Table creation check
    assert "CREATE TABLE IF NOT EXISTS wire_transfers" in init_sql_content

    # 2. Key columns and constraints
    assert "wire_id UUID PRIMARY KEY" in init_sql_content
    assert "client_id VARCHAR(64) NOT NULL" in init_sql_content
    assert "idempotency_key VARCHAR(128) NOT NULL" in init_sql_content
    assert "amount_cents BIGINT NOT NULL CHECK (amount_cents > 0)" in init_sql_content
    assert "status VARCHAR(32) NOT NULL DEFAULT 'processing'" in init_sql_content
    assert (
        "CONSTRAINT uq_wire_idempotency UNIQUE (client_id, idempotency_key)"
        in init_sql_content
    )


def test_partial_index_for_in_flight_wires(init_sql_content: str) -> None:
    """Verify partial index on active status excludes terminal states."""
    # 1. Partial index definition check
    assert "CREATE INDEX IF NOT EXISTS idx_wire_in_flight_status" in init_sql_content
    assert "ON wire_transfers (status, created_at)" in init_sql_content
    assert "WHERE status IN ('processing', 'submitted_to_bank');" in init_sql_content


def test_ledger_journal_table_schema(init_sql_content: str) -> None:
    """Verify immutable dual-entry ledger journal schema and constraints."""
    # 1. Table creation check
    assert "CREATE TABLE IF NOT EXISTS ledger_journal" in init_sql_content

    # 2. Key columns, foreign keys, and directions
    assert "entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v4()" in init_sql_content
    assert (
        "wire_id UUID NOT NULL REFERENCES wire_transfers(wire_id) ON DELETE RESTRICT"
        in init_sql_content
    )
    assert (
        "direction VARCHAR(8) NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT'))"
        in init_sql_content
    )
    assert (
        "CREATE INDEX IF NOT EXISTS idx_ledger_wire_id ON ledger_journal(wire_id);"
        in init_sql_content
    )


def test_wire_audit_log_table_schema(init_sql_content: str) -> None:
    """Verify wire audit log tracking table schema and index."""
    # 1. Table creation check
    assert "CREATE TABLE IF NOT EXISTS wire_audit_log" in init_sql_content

    # 2. Key columns and index
    assert "audit_id BIGSERIAL PRIMARY KEY" in init_sql_content
    assert (
        "wire_id UUID NOT NULL REFERENCES wire_transfers(wire_id) ON DELETE CASCADE"
        in init_sql_content
    )
    assert (
        "CREATE INDEX IF NOT EXISTS idx_audit_wire_id ON wire_audit_log(wire_id);"
        in init_sql_content
    )


def test_index_deduplication_invariant(init_sql_content: str) -> None:
    """Verify no redundant CREATE INDEX exists for PK or UNIQUE constraint columns."""
    # 1. Verify no explicit redundant index on wire_transfers(wire_id)
    pattern_pk_index = re.compile(
        r"CREATE\s+INDEX\s+.*ON\s+wire_transfers\s*\(\s*wire_id\s*\)",
        re.IGNORECASE,
    )
    assert not pattern_pk_index.search(init_sql_content), (
        "Redundant index on wire_transfers(wire_id) detected; PK already has an implicit B-Tree index"
    )

    # 2. Verify no explicit redundant index on wire_transfers(client_id, idempotency_key)
    pattern_unique_index = re.compile(
        r"CREATE\s+INDEX\s+.*ON\s+wire_transfers\s*\(\s*client_id\s*,\s*idempotency_key\s*\)",
        re.IGNORECASE,
    )
    assert not pattern_unique_index.search(init_sql_content), (
        "Redundant index on unique constraint (client_id, idempotency_key) detected"
    )
