-- Migration 010: Add unique constraints to scheduled_messages for idempotency
-- Created: 2025-12-24
-- Purpose: Ensure exactly one job per event/message-type or shift/message-type

-- ===========================
--  UNIQUE CONSTRAINTS
-- ===========================

-- For event-based jobs (INIT, TECH_REMINDER): unique on (org_id, message_type, event_id)
-- where shift_id is null
CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduled_messages_unique_event_job
    ON scheduled_messages(org_id, message_type, event_id)
    WHERE shift_id IS NULL;

-- For shift-based jobs (SHIFT_REMINDER): unique on (org_id, message_type, shift_id)
-- where event_id may or may not be null
CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduled_messages_unique_shift_job
    ON scheduled_messages(org_id, message_type, shift_id)
    WHERE shift_id IS NOT NULL;

-- Comment
COMMENT ON INDEX idx_scheduled_messages_unique_event_job IS 
    'Ensures exactly one scheduled message per event and message type (INIT, TECH_REMINDER)';

COMMENT ON INDEX idx_scheduled_messages_unique_shift_job IS 
    'Ensures exactly one scheduled message per shift and message type (SHIFT_REMINDER)';
