-- ==============================================================================
-- Schema: card_disputes
-- Module: 05_application_integration (Card Dispute & Chargeback Lifecycle Engine)
-- ==============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Card Disputes Table
CREATE TABLE IF NOT EXISTS card_disputes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id VARCHAR(64) NOT NULL UNIQUE,
    card_token VARCHAR(64) NOT NULL,
    card_last_four VARCHAR(4) NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    reason VARCHAR(50) NOT NULL,
    evidence_notes TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'processing' CHECK (
        status IN ('pending', 'processing', 'submitted_to_network', 'failed', 'cancelled')
    ),
    celery_task_id VARCHAR(64),
    network_reference_id VARCHAR(64),
    attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count >= 1),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Partial Index for In-Flight State Machine Optimization
-- Eliminates write amplification and cache bloat on terminal states (submitted_to_network, failed, cancelled)
CREATE INDEX IF NOT EXISTS idx_card_disputes_active_status
    ON card_disputes (status)
    WHERE status IN ('pending', 'processing');

-- 3. Temporal Index for Ingestion Auditing & Ledger Queries
CREATE INDEX IF NOT EXISTS idx_card_disputes_created_at
    ON card_disputes (created_at DESC);
