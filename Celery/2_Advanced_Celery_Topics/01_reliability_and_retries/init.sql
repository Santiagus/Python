CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_reference VARCHAR(255) NOT NULL UNIQUE,
    balance NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    provider_transaction_id VARCHAR(255) UNIQUE,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    status VARCHAR(32) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'syncing', 'succeeded', 'failed', 'unknown')),
    provider_status VARCHAR(64),
    sync_attempts INTEGER NOT NULL DEFAULT 0 CHECK (sync_attempts >= 0),
    last_synced_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sync_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES transactions(id),
    celery_task_id VARCHAR(255) NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    outcome VARCHAR(32) NOT NULL,
    provider_http_status INTEGER,
    error_type VARCHAR(255),
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    UNIQUE (transaction_id, attempt_number)
);

CREATE INDEX transactions_status_retry_idx
    ON transactions (status, next_retry_at);

CREATE INDEX sync_attempts_transaction_idx
    ON sync_attempts (transaction_id);

CREATE OR REPLACE FUNCTION validate_transaction_currency()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM accounts
        WHERE id = NEW.account_id
          AND currency = NEW.currency
    ) THEN
        RAISE EXCEPTION 'Transaction currency must match the account currency';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER transactions_currency_check
    BEFORE INSERT OR UPDATE OF account_id, currency ON transactions
    FOR EACH ROW
    EXECUTE FUNCTION validate_transaction_currency();
