-- Schema definition for Module 02: Financial Document & KYC Underwriting Pipeline
-- PostgreSQL 16 compatible DDL with UUID v4, JSONB metrics, check constraints, and triggers

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Commercial Credit Applications
CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name VARCHAR(255) NOT NULL,
    applicant_name VARCHAR(255) NOT NULL,
    requested_facility NUMERIC(14, 2) NOT NULL CHECK (requested_facility > 0),
    status VARCHAR(32) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'validating', 'processing', 'approved', 'declined', 'manual_review', 'failed')),
    workflow_id VARCHAR(255),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Ingested Dossier Documents (KYC ID, Bank Statement, Tax Return)
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    doc_type VARCHAR(32) NOT NULL
        CHECK (doc_type IN ('kyc_id', 'bank_statement', 'tax_filing')),
    file_path VARCHAR(512) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes >= 0),
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'validating', 'processed', 'degraded', 'failed')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Partitioned Document Pages (for parallel statement processing in chord header)
CREATE TABLE document_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    status VARCHAR(32) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'processed', 'degraded', 'failed')),
    ocr_confidence NUMERIC(5, 4) CHECK (ocr_confidence >= 0.0 AND ocr_confidence <= 1.0),
    extracted_text TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, page_number)
);

-- 4. Underwriting Decision Memos (Fan-in aggregation callback result)
CREATE TABLE underwriting_memos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
    decision VARCHAR(32) NOT NULL
        CHECK (decision IN ('approved', 'declined', 'manual_review')),
    calculated_dscr NUMERIC(6, 3),
    net_cashflow NUMERIC(14, 2),
    total_revenue NUMERIC(14, 2),
    audit_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT NOT NULL,
    stage_timings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- High-performance indexes for polling and foreign key lookups
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_documents_application_id ON documents(application_id);
CREATE INDEX idx_document_pages_document_id ON document_pages(document_id);
CREATE INDEX idx_underwriting_memos_application_id ON underwriting_memos(application_id);
CREATE INDEX idx_underwriting_memos_decision ON underwriting_memos(decision);

-- Auto-update trigger for updated_at timestamps
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_applications_updated_at
    BEFORE UPDATE ON applications
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_document_pages_updated_at
    BEFORE UPDATE ON document_pages
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_underwriting_memos_updated_at
    BEFORE UPDATE ON underwriting_memos
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

