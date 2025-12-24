-- Migration 006: Add next_followup_at to events table
-- This field stores when the next follow-up message should be sent for events with status "follow_up"

-- Add next_followup_at column to events table
ALTER TABLE events ADD COLUMN IF NOT EXISTS next_followup_at TIMESTAMPTZ;

-- Add index for efficient queries on next_followup_at
CREATE INDEX IF NOT EXISTS idx_events_next_followup ON events(org_id, next_followup_at) WHERE next_followup_at IS NOT NULL;

-- Add comment to document the field
COMMENT ON COLUMN events.next_followup_at IS 'When the next follow-up message should be sent (for status=follow_up events)';
