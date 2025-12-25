-- Migration 012: Scheduler Heartbeat Tracking
-- Created: 2025-12-25
-- Purpose: Track scheduler cron health and connectivity

-- ===========================
--  SCHEDULER HEARTBEAT TABLE
-- ===========================

CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
    org_id                   BIGINT PRIMARY KEY REFERENCES orgs(org_id) ON DELETE CASCADE,
    
    -- Last run information
    last_run_at              TIMESTAMPTZ NOT NULL,
    last_run_status          TEXT NOT NULL DEFAULT 'ok',  -- ok, error, warning
    last_run_duration_ms     INTEGER,
    
    -- Job processing stats from last run
    last_run_due_found       INTEGER DEFAULT 0,
    last_run_sent            INTEGER DEFAULT 0,
    last_run_failed          INTEGER DEFAULT 0,
    last_run_skipped         INTEGER DEFAULT 0,
    last_run_blocked         INTEGER DEFAULT 0,
    last_run_postponed       INTEGER DEFAULT 0,
    
    -- Error tracking
    last_error               TEXT,
    last_error_at            TIMESTAMPTZ,
    
    -- Deployment tracking (optional)
    last_commit_sha          TEXT,
    
    -- Timestamps
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Constraints
    CHECK (last_run_status IN ('ok', 'error', 'warning'))
);

-- Index for checking stale heartbeats
CREATE INDEX IF NOT EXISTS idx_scheduler_heartbeat_last_run_at 
    ON scheduler_heartbeat(last_run_at);

-- ===========================
--  COMMENTS
-- ===========================

COMMENT ON TABLE scheduler_heartbeat IS 'Tracks scheduler cron health and connectivity for monitoring';
COMMENT ON COLUMN scheduler_heartbeat.last_run_at IS 'Timestamp of last successful scheduler run';
COMMENT ON COLUMN scheduler_heartbeat.last_run_status IS 'Status of last run: ok, error, or warning';
COMMENT ON COLUMN scheduler_heartbeat.last_run_duration_ms IS 'Duration of last run in milliseconds';
