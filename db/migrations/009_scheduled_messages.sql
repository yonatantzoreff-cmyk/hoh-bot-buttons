-- Migration 009: Scheduled Messages and Scheduler Settings
-- Created: 2025-12-24
-- Purpose: Add tables for scheduled message delivery and per-org scheduler configuration

-- ===========================
--  SCHEDULED MESSAGES TABLE
-- ===========================

CREATE TABLE IF NOT EXISTS scheduled_messages (
    job_id                   TEXT PRIMARY KEY,  -- Unique job identifier
    org_id                   BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    
    -- Message type and context
    message_type             TEXT NOT NULL,  -- INIT, TECH_REMINDER, SHIFT_REMINDER
    event_id                 BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    shift_id                 BIGINT REFERENCES employee_shifts(shift_id) ON DELETE CASCADE,
    
    -- Scheduling info
    send_at                  TIMESTAMPTZ NOT NULL,
    
    -- Status tracking
    status                   TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled, paused, blocked, retrying, sent, failed, skipped
    is_enabled               BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Retry logic
    attempt_count            INTEGER NOT NULL DEFAULT 0,
    max_attempts             INTEGER NOT NULL DEFAULT 3,
    
    -- Error tracking
    last_error               TEXT,
    
    -- Delivery tracking
    sent_at                  TIMESTAMPTZ,
    
    -- Resolution tracking (who was the message sent to)
    last_resolved_to_name    TEXT,
    last_resolved_to_phone   TEXT,
    
    -- Timestamps
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Constraints
    CHECK (message_type IN ('INIT', 'TECH_REMINDER', 'SHIFT_REMINDER')),
    CHECK (status IN ('scheduled', 'paused', 'blocked', 'retrying', 'sent', 'failed', 'skipped'))
);

-- Indexes for scheduled_messages
CREATE INDEX IF NOT EXISTS idx_scheduled_messages_org_id 
    ON scheduled_messages(org_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_messages_send_at 
    ON scheduled_messages(send_at) 
    WHERE status IN ('scheduled', 'retrying');

CREATE INDEX IF NOT EXISTS idx_scheduled_messages_org_status 
    ON scheduled_messages(org_id, status);

CREATE INDEX IF NOT EXISTS idx_scheduled_messages_event_id 
    ON scheduled_messages(event_id) 
    WHERE event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scheduled_messages_shift_id 
    ON scheduled_messages(shift_id) 
    WHERE shift_id IS NOT NULL;

-- ===========================
--  SCHEDULER SETTINGS TABLE
-- ===========================

CREATE TABLE IF NOT EXISTS scheduler_settings (
    org_id                   BIGINT PRIMARY KEY REFERENCES orgs(org_id) ON DELETE CASCADE,
    
    -- Global and per-message-type enable flags
    enabled_global           BOOLEAN NOT NULL DEFAULT TRUE,
    enabled_init             BOOLEAN NOT NULL DEFAULT TRUE,
    enabled_tech             BOOLEAN NOT NULL DEFAULT TRUE,
    enabled_shift            BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- INIT message settings (initial contact)
    init_days_before         INTEGER NOT NULL DEFAULT 28,
    init_send_time           TIME NOT NULL DEFAULT '10:00',
    
    -- TECH_REMINDER settings (technical reminder)
    tech_days_before         INTEGER NOT NULL DEFAULT 2,
    tech_send_time           TIME NOT NULL DEFAULT '12:00',
    
    -- SHIFT_REMINDER settings (shift reminder)
    shift_days_before        INTEGER NOT NULL DEFAULT 1,
    shift_send_time          TIME NOT NULL DEFAULT '12:00',
    
    -- Timestamps
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===========================
--  COMMENTS
-- ===========================

COMMENT ON TABLE scheduled_messages IS 'Scheduled messages for events and shifts with retry logic';
COMMENT ON COLUMN scheduled_messages.job_id IS 'Unique job identifier for the scheduled message';
COMMENT ON COLUMN scheduled_messages.message_type IS 'Type of message: INIT, TECH_REMINDER, or SHIFT_REMINDER';
COMMENT ON COLUMN scheduled_messages.status IS 'Current status: scheduled, paused, blocked, retrying, sent, failed, or skipped';
COMMENT ON COLUMN scheduled_messages.attempt_count IS 'Number of delivery attempts made';
COMMENT ON COLUMN scheduled_messages.max_attempts IS 'Maximum number of delivery attempts allowed';

COMMENT ON TABLE scheduler_settings IS 'Per-organization scheduler configuration for automated messages';
COMMENT ON COLUMN scheduler_settings.enabled_global IS 'Master switch for all scheduled messages in this org';
COMMENT ON COLUMN scheduler_settings.init_days_before IS 'Days before event to send initial contact message';
COMMENT ON COLUMN scheduler_settings.tech_days_before IS 'Days before event to send technical reminder';
COMMENT ON COLUMN scheduler_settings.shift_days_before IS 'Days before shift to send shift reminder';
