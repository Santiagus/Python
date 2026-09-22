-- =============================================================================
-- Multi-Rail Payment Orchestrator & Batch Settlement Engine
-- Database Initialization & DDL Schema
-- Module 03: Routing and Capacity
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 1. Accounts Table
-- Stores source enterprise funding accounts with balance in minor units (cents)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_number VARCHAR(32) NOT NULL UNIQUE,
    account_mask VARCHAR(16) NOT NULL,
    balance_cents BIGINT NOT NULL CHECK (balance_cents >= 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 2. Payments Table
-- Real-time instant payouts (FedNow/RTP) and individual payment records
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    payment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    source_account_id UUID NOT NULL REFERENCES accounts(account_id),
    destination_account_number VARCHAR(32) NOT NULL,
    destination_routing_number VARCHAR(16) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    rail VARCHAR(16) NOT NULL CHECK (rail IN ('fednow', 'rtp', 'ach')),
    priority VARCHAR(16) NOT NULL CHECK (priority IN ('critical', 'default', 'bulk')),
    status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'settled', 'failed', 'rejected')),
    cleared_at TIMESTAMPTZ,
    error_detail TEXT,
    external_reference VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 3. Batch Settlements Table
-- High-volume payroll and supplier disbursement batch metadata
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS batch_settlements (
    batch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_reference VARCHAR(128) NOT NULL,
    source_account_id UUID NOT NULL REFERENCES accounts(account_id),
    total_items INTEGER NOT NULL CHECK (total_items > 0),
    total_amount_cents BIGINT NOT NULL CHECK (total_amount_cents > 0),
    processed_items INTEGER NOT NULL DEFAULT 0 CHECK (processed_items >= 0),
    status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'partially_failed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 4. Disbursements Table
-- Granular line items within a batch settlement file
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS disbursements (
    disbursement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES batch_settlements(batch_id) ON DELETE CASCADE,
    recipient_name VARCHAR(128) NOT NULL,
    account_number VARCHAR(32) NOT NULL,
    routing_number VARCHAR(16) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'settled', 'failed', 'rejected')),
    error_detail TEXT,
    external_reference VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Indexes for High-Concurrency Performance
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_payments_source_account ON payments(source_account_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_idempotency ON payments(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_batch_settlements_source ON batch_settlements(source_account_id);
CREATE INDEX IF NOT EXISTS idx_batch_settlements_status ON batch_settlements(status);
CREATE INDEX IF NOT EXISTS idx_disbursements_batch_id ON disbursements(batch_id);
CREATE INDEX IF NOT EXISTS idx_disbursements_status ON disbursements(status);

-- -----------------------------------------------------------------------------
-- Specimen Seed Accounts
-- Deterministic UUIDs for turnkey Swagger UI and REST Client execution
-- -----------------------------------------------------------------------------
INSERT INTO accounts (account_id, account_number, account_mask, balance_cents, currency)
VALUES
    ('a0000000-0000-0000-0000-000000000001', '1000112233445501', '******5501', 1000000000, 'USD'), -- $10,000,000.00
    ('a0000000-0000-0000-0000-000000000002', '2000223344556602', '******6602', 500000000, 'USD'),  -- $5,000,000.00
    ('a0000000-0000-0000-0000-000000000003', '3000334455667703', '******7703', 10000000, 'USD'),   -- $100,000.00
    ('a0000000-0000-0000-0000-000000000004', '4000445566778804', '******8804', 5000, 'USD')        -- $50.00 (Depleted)
ON CONFLICT (account_id) DO NOTHING;

-- Seed enterprise account pool (1..100) for concurrent multi-client load testing
INSERT INTO accounts (account_id, account_number, account_mask, balance_cents, currency)
SELECT
    ('a0000000-0000-0000-0000-' || LPAD(i::text, 12, '0'))::uuid,
    '1000' || LPAD(i::text, 12, '0'),
    '******' || RIGHT(LPAD(i::text, 12, '0'), 4),
    1000000000, -- $10,000,000.00
    'USD'
FROM generate_series(1, 100) AS i
ON CONFLICT (account_id) DO NOTHING;


