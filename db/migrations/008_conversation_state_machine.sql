-- Migration 008: Add conversation state machine fields
-- Purpose: Implement strict state machine for WhatsApp flow to prevent free text progression

-- Add state machine fields to conversations table
ALTER TABLE conversations 
ADD COLUMN IF NOT EXISTS expected_input TEXT NOT NULL DEFAULT 'interactive',
ADD COLUMN IF NOT EXISTS last_prompt_key TEXT,
ADD COLUMN IF NOT EXISTS last_template_sid TEXT,
ADD COLUMN IF NOT EXISTS last_template_vars JSONB;

-- Create index for faster state lookups
CREATE INDEX IF NOT EXISTS idx_conversations_expected_input 
ON conversations(org_id, expected_input);

-- Add comment for documentation
COMMENT ON COLUMN conversations.expected_input IS 'Expected input type: interactive, contact_required, free_text_allowed, paused';
COMMENT ON COLUMN conversations.last_prompt_key IS 'Last prompt sent (init, ranges, halves, contact_prompt, not_sure, confirm)';
COMMENT ON COLUMN conversations.last_template_sid IS 'Twilio Content SID of last template sent';
COMMENT ON COLUMN conversations.last_template_vars IS 'Variables used in last template send';
