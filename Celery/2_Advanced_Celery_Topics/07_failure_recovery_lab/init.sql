-- Database Schema: 07_failure_recovery_lab (PostgreSQL 16)
-- High-Value Interbank Wire & Treasury Settlement Gateway

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Master Wire Transfers Ledger Table
CREATE TABLE IF NOT EXISTS wire_transfers (
    wire_id UUID PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    sender_account_mask VARCHAR(32) NOT NULL,
    beneficiary_account_mask VARCHAR(32) NOT NULL,
    routing_number VARCHAR(9) NOT NULL,
    swift_bic VARCHAR(11) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'processing',
    delivery_attempts INT NOT NULL DEFAULT 1,
    redelivered_flag BOOLEAN NOT NULL DEFAULT FALSE,
    bank_reference_id VARCHAR(128),
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    settled_at TIMESTAMPTZ,
    CONSTRAINT uq_wire_idempotency UNIQUE (client_id, idempotency_key)
);

-- Partial B-Tree Index for In-Flight Transactions (Anti-Blackhole & High-Throughput Write)
-- Excludes terminal states ('settled', 'failed', 'dead_lettered') to minimize index write amplification
CREATE INDEX IF NOT EXISTS idx_wire_in_flight_status 
ON wire_transfers (status, created_at) 
WHERE status IN ('processing', 'submitted_to_bank');

-- 2. Immutable Ledger Journal Table (Dual-Entry Balancing)
CREATE TABLE IF NOT EXISTS ledger_journal (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    wire_id UUID NOT NULL REFERENCES wire_transfers(wire_id) ON DELETE RESTRICT,
    account_type VARCHAR(32) NOT NULL, -- 'customer_cash' or 'clearinghouse_settlement'
    direction VARCHAR(8) NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ledger_wire_id ON ledger_journal(wire_id);

-- 3. Comprehensive Wire Audit Log (Failure Recovery Tracking)
CREATE TABLE IF NOT EXISTS wire_audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    wire_id UUID NOT NULL REFERENCES wire_transfers(wire_id) ON DELETE CASCADE,
    previous_status VARCHAR(32),
    new_status VARCHAR(32) NOT NULL,
    worker_hostname VARCHAR(128),
    redelivered BOOLEAN DEFAULT FALSE,
    event_description TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_wire_id ON wire_audit_log(wire_id);

