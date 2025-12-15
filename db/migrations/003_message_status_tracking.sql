-- Message status tracking fields
-- Migration 003
-- Adds delivery/read/failure timestamps and status columns to messages.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS status TEXT,
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_status_at TIMESTAMPTZ;
