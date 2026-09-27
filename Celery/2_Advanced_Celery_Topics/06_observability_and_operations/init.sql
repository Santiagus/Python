-- 06_observability_and_operations / init.sql
-- Master DDL for Real-Time Fraud & AML Screening Rail

-- 1. Master Screenings Table (ACID Financial Ledger)
CREATE TABLE IF NOT EXISTS screenings (
    id UUID PRIMARY KEY,
    transaction_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    client_ip VARCHAR(45) NOT NULL,
    risk_score INT DEFAULT NULL CHECK (risk_score >= 0 AND risk_score <= 100),
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    decision_reason VARCHAR(255) DEFAULT NULL,
    latency_ms NUMERIC(8, 2) DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_screenings_tx UNIQUE (transaction_id),
    CONSTRAINT ck_screening_status CHECK (
        status IN ('pending', 'processing', 'approved', 'flagged_review', 'blocked', 'failed')
    )
);

-- 2. Partial B-Tree Index for In-Flight State Visibility
-- Eliminates write amplification on terminal states - keeps active records in CPU L3 cache
CREATE INDEX IF NOT EXISTS idx_screenings_active_status 
ON screenings (created_at DESC) 
WHERE status IN ('pending', 'processing');

-- 3. Watchlist Hits Table (Compliance Sanctions Audit)
CREATE TABLE IF NOT EXISTS watchlist_hits (
    id UUID PRIMARY KEY,
    screening_id UUID NOT NULL REFERENCES screenings(id) ON DELETE CASCADE,
    entity_name VARCHAR(255) NOT NULL,
    watchlist_type VARCHAR(32) NOT NULL, -- 'OFAC_SDN', 'EU_SANCTIONS', 'PEP'
    match_confidence NUMERIC(5, 2) NOT NULL, -- e.g. 98.50
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watchlist_hits_screening_id 
ON watchlist_hits (screening_id);

-- 4. Operational Audit Log (Diagnostic Event Store)
CREATE TABLE IF NOT EXISTS operational_events (
    id UUID PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64) DEFAULT NULL,
    event_type VARCHAR(64) NOT NULL, -- 'QUEUE_AGE_BREACH', 'EXTERNAL_TIMEOUT', 'CIRCUIT_BREAKER_OPEN'
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operational_events_correlation 
ON operational_events (correlation_id);
