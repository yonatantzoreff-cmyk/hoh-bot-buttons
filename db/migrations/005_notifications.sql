-- Migration 005: User notification state for tracking unread messages
-- This table tracks the last seen message for each user/admin to calculate unread counts

CREATE TABLE IF NOT EXISTS user_notification_state (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL DEFAULT 'admin', -- For now, using 'admin' as default until auth is implemented
    last_seen_message_id BIGINT,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_notification_state_org_user ON user_notification_state(org_id, user_id);
