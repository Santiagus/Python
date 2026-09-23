-- =============================================================================
-- EOD Banking Cut-Off & Ledger Reconciliation Engine
-- Database Initialization & DDL Schema
-- Module 04: Scheduling
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 1. Accounts Table
-- Stores internal corporate and treasury ledger accounts
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_number VARCHAR(32) NOT NULL UNIQUE,
    account_mask VARCHAR(16) NOT NULL,
    account_type VARCHAR(32) NOT NULL DEFAULT 'operating' CHECK (account_type IN ('operating', 'settlement', 'reserve', 'clearing')),
    balance_cents BIGINT NOT NULL CHECK (balance_cents >= 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 2. Ledger Entries Table
-- Double-entry posted financial movements assigned to a banking business period
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    direction VARCHAR(8) NOT NULL CHECK (direction IN ('credit', 'debit')),
    status VARCHAR(16) NOT NULL DEFAULT 'posted' CHECK (status IN ('pending', 'posted', 'cleared', 'cancelled')),
    period_date DATE NOT NULL,
    description VARCHAR(255) NOT NULL DEFAULT '',
    external_reference VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 3. Reconciliation Reports Table
-- Sealed, immutable daily financial reports enforcing strict UNIQUE (period_date)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reconciliation_reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period_date DATE NOT NULL UNIQUE,
    total_credits_cents BIGINT NOT NULL DEFAULT 0 CHECK (total_credits_cents >= 0),
    total_debits_cents BIGINT NOT NULL DEFAULT 0 CHECK (total_debits_cents >= 0),
    net_movement_cents BIGINT NOT NULL DEFAULT 0,
    discrepancy_cents BIGINT NOT NULL DEFAULT 0 CHECK (discrepancy_cents >= 0),
    status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'balanced', 'discrepancy_detected', 'failed')),
    verification_hash VARCHAR(64) NOT NULL DEFAULT '',
    reconciled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 4. Idempotency Records Table
-- Ephemeral request coordination and audit deduplication with explicit TTL
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS idempotency_records (
    key VARCHAR(128) PRIMARY KEY,
    scope VARCHAR(64) NOT NULL DEFAULT 'general',
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Partial & Deduplicated Indexes for High Performance
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_ledger_entries_period_status ON ledger_entries(period_date, status);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_account_id ON ledger_entries(account_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_reports_pending ON reconciliation_reports(period_date) WHERE status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS idx_idempotency_records_expires_at ON idempotency_records(expires_at);

-- -----------------------------------------------------------------------------
-- Specimen Seed Data
-- Turnkey accounts for development, interactive testing, and E2E verification
-- -----------------------------------------------------------------------------
INSERT INTO accounts (account_id, account_number, account_mask, account_type, balance_cents, currency)
VALUES
    ('c0000000-0000-0000-0000-000000000001', '1000112233440001', '******0001', 'operating', 250000000, 'USD'),  -- $2,500,000.00
    ('c0000000-0000-0000-0000-000000000002', '2000223344550002', '******0002', 'settlement', 500000000, 'USD'), -- $5,000,000.00
    ('c0000000-0000-0000-0000-000000000003', '3000334455660003', '******0003', 'reserve', 100000000, 'USD')     -- $1,000,000.00
ON CONFLICT (account_id) DO NOTHING;

