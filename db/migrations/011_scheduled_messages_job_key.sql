-- Migration 011: Add job_key column and convert job_id to BIGINT identity
-- Created: 2025-12-24
-- Purpose: Fix schema mismatch - job_id should be BIGINT identity, job_key holds string identifiers

-- ===========================
--  STEP 1: Add job_key column
-- ===========================

-- Add job_key column to hold the string identifier
ALTER TABLE scheduled_messages 
ADD COLUMN IF NOT EXISTS job_key TEXT;

-- ===========================
--  STEP 2: Migrate existing data
-- ===========================

-- Copy existing job_id values to job_key (for any existing rows)
UPDATE scheduled_messages 
SET job_key = job_id 
WHERE job_key IS NULL;

-- ===========================
--  STEP 3: Recreate job_id as BIGINT identity
-- ===========================

-- Drop the primary key constraint on job_id
ALTER TABLE scheduled_messages 
DROP CONSTRAINT IF EXISTS scheduled_messages_pkey;

-- Drop the old job_id column (it was TEXT)
ALTER TABLE scheduled_messages 
DROP COLUMN IF EXISTS job_id;

-- Add new job_id column as BIGINT with IDENTITY
ALTER TABLE scheduled_messages 
ADD COLUMN job_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY;

-- ===========================
--  STEP 4: Add unique constraint on (org_id, job_key)
-- ===========================

-- Make job_key NOT NULL now that migration is complete
ALTER TABLE scheduled_messages 
ALTER COLUMN job_key SET NOT NULL;

-- Add unique index on (org_id, job_key) for idempotency
CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduled_messages_unique_job_key
    ON scheduled_messages(org_id, job_key);

-- ===========================
--  COMMENTS
-- ===========================

COMMENT ON COLUMN scheduled_messages.job_id IS 'Auto-generated unique numeric identifier (PRIMARY KEY)';
COMMENT ON COLUMN scheduled_messages.job_key IS 'Deterministic string key for idempotency (org_X_event_Y_TYPE_hash)';
COMMENT ON INDEX idx_scheduled_messages_unique_job_key IS 
    'Ensures idempotency - one job per unique job_key within an org';
