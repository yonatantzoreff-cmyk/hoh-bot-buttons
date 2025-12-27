-- Recurring Availability Feature - Employee Unavailability Rules & Exceptions
-- Migration 013
-- Created: 2025-12-27

-- ===========================
--  EMPLOYEE UNAVAILABILITY RULES TABLE
-- ===========================
-- Stores recurring patterns for employee unavailability

CREATE TABLE IF NOT EXISTS employee_unavailability_rules (
    rule_id         BIGSERIAL PRIMARY KEY,
    org_id          BIGINT NOT NULL REFERENCES orgs(org_id) ON DELETE CASCADE,
    employee_id     BIGINT NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,
    
    -- Pattern configuration
    pattern         TEXT NOT NULL CHECK (pattern IN ('weekly', 'biweekly', 'monthly')),
    anchor_date     DATE NOT NULL,          -- For biweekly calculations (default = start_date)
    days_of_week    INTEGER[],              -- Array of days: 0=Sunday, 1=Monday, ..., 6=Saturday
    day_of_month    INTEGER,                -- Day of month (1-31) for monthly pattern
    
    -- Time configuration
    all_day         BOOLEAN NOT NULL DEFAULT FALSE,
    start_time      TIME,                   -- Start time for partial day unavailability
    end_time        TIME,                   -- End time for partial day unavailability
    notes           TEXT,                   -- Reason for recurring unavailability
    
    -- Validity period
    start_date      DATE NOT NULL,          -- When this rule starts
    until_date      DATE,                   -- Optional end date (null = indefinite)
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_employee_unavailability_rules_org_employee 
    ON employee_unavailability_rules(org_id, employee_id);
    
CREATE INDEX IF NOT EXISTS idx_employee_unavailability_rules_dates 
    ON employee_unavailability_rules(org_id, start_date, until_date);

-- ===========================
--  EMPLOYEE UNAVAILABILITY EXCEPTIONS TABLE
-- ===========================
-- Stores exceptions to recurring rules (cancels occurrence on specific date)

CREATE TABLE IF NOT EXISTS employee_unavailability_exceptions (
    exception_id    BIGSERIAL PRIMARY KEY,
    rule_id         BIGINT NOT NULL REFERENCES employee_unavailability_rules(rule_id) ON DELETE CASCADE,
    date            DATE NOT NULL,          -- Date to exclude from rule occurrences
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    UNIQUE(rule_id, date)
);

CREATE INDEX IF NOT EXISTS idx_employee_unavailability_exceptions_rule 
    ON employee_unavailability_exceptions(rule_id);

-- ===========================
--  ENHANCE EMPLOYEE_UNAVAILABILITY TABLE
-- ===========================
-- Add optional fields to track source of unavailability (for debugging)

ALTER TABLE employee_unavailability 
    ADD COLUMN IF NOT EXISTS source_type TEXT CHECK (source_type IN ('manual', 'rule')),
    ADD COLUMN IF NOT EXISTS source_rule_id BIGINT REFERENCES employee_unavailability_rules(rule_id) ON DELETE SET NULL;

-- Backfill existing records as manual
UPDATE employee_unavailability 
SET source_type = 'manual' 
WHERE source_type IS NULL;

CREATE INDEX IF NOT EXISTS idx_employee_unavailability_source 
    ON employee_unavailability(org_id, source_type, source_rule_id);

-- ===========================
--  COMMENTS
-- ===========================

COMMENT ON TABLE employee_unavailability_rules IS 'Recurring patterns for employee unavailability (weekly/biweekly/monthly)';
COMMENT ON TABLE employee_unavailability_exceptions IS 'Exceptions to recurring rules - cancels occurrence on specific date';

COMMENT ON COLUMN employee_unavailability_rules.pattern IS 'Type of recurrence: weekly, biweekly, or monthly';
COMMENT ON COLUMN employee_unavailability_rules.anchor_date IS 'Reference date for biweekly calculation (week 0)';
COMMENT ON COLUMN employee_unavailability_rules.days_of_week IS 'Array of weekday numbers (0=Sun, 6=Sat) for weekly/biweekly';
COMMENT ON COLUMN employee_unavailability_rules.day_of_month IS 'Day of month (1-31) for monthly pattern';
COMMENT ON COLUMN employee_unavailability_rules.all_day IS 'True if unavailable all day, false if partial hours';

COMMENT ON COLUMN employee_unavailability.source_type IS 'Origin of unavailability: manual (user entered) or rule (from recurring pattern)';
COMMENT ON COLUMN employee_unavailability.source_rule_id IS 'Reference to the rule that generated this entry (if source_type=rule)';
