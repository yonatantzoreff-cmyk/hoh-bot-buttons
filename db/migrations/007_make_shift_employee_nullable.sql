-- Migration 007: Make employee_id nullable in employee_shifts
-- PHASE 2: Allow shifts without assigned employees
-- This enables "Add Shift" to create empty shifts that can be filled later

-- Remove the existing foreign key constraint so we can modify the column
-- We'll re-add it with the same behavior but allowing NULL values
ALTER TABLE employee_shifts 
    DROP CONSTRAINT IF EXISTS employee_shifts_employee_id_fkey;

-- Make employee_id nullable
ALTER TABLE employee_shifts 
    ALTER COLUMN employee_id DROP NOT NULL;

-- Re-add foreign key constraint but allow NULL
ALTER TABLE employee_shifts 
    ADD CONSTRAINT employee_shifts_employee_id_fkey 
    FOREIGN KEY (employee_id) 
    REFERENCES employees(employee_id) 
    ON DELETE CASCADE;

-- Drop the old unique constraint on (event_id, employee_id)
ALTER TABLE employee_shifts 
    DROP CONSTRAINT IF EXISTS employee_shifts_event_id_employee_id_key;

-- Add a new unique constraint that only applies when employee_id is NOT NULL
-- This prevents duplicate employee assignments to the same event
CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_shifts_event_employee 
    ON employee_shifts(event_id, employee_id) 
    WHERE employee_id IS NOT NULL;

COMMENT ON COLUMN employee_shifts.employee_id IS 'Employee assigned to this shift (NULL if unassigned)';
