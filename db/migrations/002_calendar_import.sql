-- Calendar Import Feature - Staging Events & Import Jobs
-- Migration 002
-- Created: 2025-12-15

-- ===========================
--  STAGING EVENTS TABLE
-- ===========================

CREATE TABLE staging_events (
    id                BIGSERIAL PRIMARY KEY,
    org_id            BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    row_index         INTEGER NOT NULL,  -- Original row number from Excel for reference
    
    -- Event data fields (mapped from Excel columns)
    date              DATE,
    show_time         TIME,
    name              TEXT,
    load_in           TIME,
    event_series      TEXT,
    producer_name     TEXT,
    producer_phone    TEXT,
    notes             TEXT,
    
    -- Validation status
    is_valid          BOOLEAN NOT NULL DEFAULT FALSE,
    errors_json       JSONB,    -- Array of error messages that block commit
    warnings_json     JSONB,    -- Array of warning messages (don't block commit)
    
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_staging_events_org_id ON staging_events(org_id);
CREATE INDEX idx_staging_events_is_valid ON staging_events(org_id, is_valid);

-- ===========================
--  UPDATE IMPORT JOBS TABLE
-- ===========================

-- Add calendar import specific fields to existing import_jobs table
-- The table already exists, we're just documenting its usage for calendar imports:
-- - job_type will be 'calendar_excel' for calendar imports
-- - source will store the original filename
-- - status: 'running', 'success', 'failed'
-- - details will store: 
--   {
--     "total_rows": N,
--     "valid_rows": N,
--     "invalid_rows": N,
--     "duplicate_warnings": [...]
--   }

-- Add a comment to document the calendar import usage
COMMENT ON TABLE import_jobs IS 'Tracks all import jobs including calendar Excel imports (job_type=calendar_excel)';

-- ===========================
--  AUDIT LOG ADDITIONS
-- ===========================

-- The audit_log table already exists and will be used for:
-- - entity_type: 'staging_event', 'calendar_import'
-- - action: 'upload', 'edit', 'delete', 'add', 'validate', 'commit', 'clear'

COMMENT ON TABLE audit_log IS 'Audit trail for all entity changes including calendar import actions';
