-- Shift Organizer Feature - Employee Unavailability & Enhanced Shifts
-- Migration 004
-- Created: 2025-12-18

-- ===========================
--  EMPLOYEE UNAVAILABILITY TABLE
-- ===========================

CREATE TABLE IF NOT EXISTS employee_unavailability (
    unavailability_id BIGSERIAL PRIMARY KEY,
    org_id            BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    employee_id       BIGINT NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,
    
    start_at          TIMESTAMPTZ NOT NULL,  -- Start of unavailability period
    end_at            TIMESTAMPTZ NOT NULL,  -- End of unavailability period
    note              TEXT,                  -- Reason for unavailability
    
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_employee_unavailability_org_employee 
    ON employee_unavailability(org_id, employee_id);
    
CREATE INDEX IF NOT EXISTS idx_employee_unavailability_org_time_range 
    ON employee_unavailability(org_id, start_at, end_at);

-- ===========================
--  ENHANCE EMPLOYEE_SHIFTS TABLE
-- ===========================

-- Add start_at and end_at for shift time tracking (needed for 10-hour rest rule)
ALTER TABLE employee_shifts 
    ADD COLUMN IF NOT EXISTS start_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS end_at TIMESTAMPTZ;

-- Add is_locked flag to prevent overwriting manual shifts during generation
ALTER TABLE employee_shifts 
    ADD COLUMN IF NOT EXISTS is_locked BOOLEAN NOT NULL DEFAULT FALSE;

-- Add shift_type for categorizing shifts (setup/show/teardown)
ALTER TABLE employee_shifts 
    ADD COLUMN IF NOT EXISTS shift_type TEXT;

-- Backfill start_at from call_time for existing records
UPDATE employee_shifts 
SET start_at = call_time 
WHERE start_at IS NULL AND call_time IS NOT NULL;

-- Add index for querying shifts by time range
CREATE INDEX IF NOT EXISTS idx_employee_shifts_employee_time_range 
    ON employee_shifts(employee_id, start_at, end_at);

-- Add index for locked shifts
CREATE INDEX IF NOT EXISTS idx_employee_shifts_locked 
    ON employee_shifts(org_id, is_locked) WHERE is_locked = TRUE;

-- ===========================
--  COMMENTS
-- ===========================

COMMENT ON TABLE employee_unavailability IS 'Tracks employee unavailability periods for shift scheduling';
COMMENT ON COLUMN employee_shifts.start_at IS 'Shift start time (for scheduling calculations)';
COMMENT ON COLUMN employee_shifts.end_at IS 'Shift end time (for scheduling calculations)';
COMMENT ON COLUMN employee_shifts.is_locked IS 'When true, prevents auto-generation from overwriting this shift';
COMMENT ON COLUMN employee_shifts.shift_type IS 'Type of shift: setup, show, teardown, or null';
