# Recurring Availability Feature - Implementation Summary

## Overview

This document summarizes the implementation of the recurring availability feature for HOH Bot, which allows defining periodic employee unavailability patterns instead of manual entry for each occurrence.

## Features Implemented

### 1. Database Schema (Migration 013)

**New Tables:**
- `employee_unavailability_rules` - Stores recurring patterns
  - Supports weekly, biweekly, and monthly patterns
  - Configurable days of week / day of month
  - Optional time ranges (all-day or partial hours)
  - Validity period (start_date to optional until_date)
  
- `employee_unavailability_exceptions` - Date-specific cancellations
  - Allows canceling a rule occurrence on specific dates
  - Cascade deletes when rule is deleted

**Enhanced Table:**
- `employee_unavailability` - Added source tracking
  - `source_type` - 'manual' or 'rule'
  - `source_rule_id` - Links to originating rule (optional)
  - Maintains backward compatibility with existing data

### 2. Backend Logic

**Rule Expansion Service** (`app/services/recurring_availability.py`)
- `expand_rule_for_month()` - Expands a rule into specific date occurrences
- `merge_unavailability()` - Applies precedence: manual overrides rule
- `check_event_conflicts()` - Detects employee conflicts with events
- Timezone-aware calculations (Asia/Jerusalem)
- Handles edge cases (invalid dates, biweekly anchor, etc.)

**Repository Methods** (`app/repositories.py`)
- `EmployeeUnavailabilityRulesRepository` - CRUD for rules
- `EmployeeUnavailabilityExceptionsRepository` - CRUD for exceptions
- Efficient bulk queries with proper indexing

### 3. API Endpoints

**Recurring Rules:**
- `POST /availability/rules` - Create recurring rule
- `DELETE /availability/rules/{rule_id}` - Delete rule

**Exceptions:**
- `POST /availability/exceptions` - Create exception for specific date
- `DELETE /availability/exceptions/{exception_id}` - Delete exception

**Enhanced Endpoints:**
- `GET /availability/month` - Returns merged view (manual + rules - exceptions)
- `GET /shift-organizer/events/{event_id}/unavailable-employees` - Check conflicts

### 4. UI Enhancements

**Availability Page** (`/ui/availability`)
- Separate sections for recurring rules vs one-time entries
- "Add Recurring Rule" modal with:
  - Employee selector
  - Pattern selector (weekly/biweekly/monthly)
  - Days of week checkboxes (for weekly/biweekly)
  - Day of month input (for monthly)
  - All-day toggle with time pickers
  - Date range configuration
  - Reason/notes field
- Visual indicators (green border for rules)
- Delete functionality for rules

### 5. Testing

**Test Coverage** (`tests/test_recurring_availability.py`)
- 11 comprehensive tests covering:
  - Weekly pattern expansion
  - Biweekly pattern with anchor date
  - Monthly pattern with invalid dates
  - Exception handling
  - Precedence logic (manual > rule)
  - Timezone handling
  - Event conflict detection
- All tests passing ✓

## Usage Examples

### Example 1: Weekly Unavailability
Employee unavailable every Sunday and Wednesday:
```json
{
  "employee_id": 5,
  "pattern": "weekly",
  "days_of_week": [0, 3],  // Sunday=0, Wednesday=3
  "all_day": true,
  "start_date": "2025-01-01",
  "notes": "Religious studies"
}
```

### Example 2: Biweekly Unavailability
Employee unavailable every other Monday:
```json
{
  "employee_id": 3,
  "pattern": "biweekly",
  "days_of_week": [1],  // Monday=1
  "anchor_date": "2025-01-06",  // First Monday
  "all_day": false,
  "start_time": "09:00",
  "end_time": "17:00",
  "start_date": "2025-01-06",
  "notes": "University classes"
}
```

### Example 3: Monthly Unavailability
Employee unavailable on the 15th of every month:
```json
{
  "employee_id": 7,
  "pattern": "monthly",
  "day_of_month": 15,
  "all_day": true,
  "start_date": "2025-01-01",
  "until_date": "2025-12-31",
  "notes": "Reserve duty"
}
```

### Example 4: Check Event Conflicts
```bash
GET /shift-organizer/events/123/unavailable-employees?org_id=1&debug=true
```

Response:
```json
{
  "event_id": 123,
  "event_name": "Concert Hall A",
  "event_date": "2025-01-15",
  "unavailable_employees": [
    {
      "employee_id": 7,
      "employee_name": "John Doe",
      "unavail_start": "2025-01-15T00:00:00+02:00",
      "unavail_end": "2025-01-15T23:59:59.999999+02:00",
      "note": "Reserve duty",
      "debug": {
        "source_type": "rule",
        "source_rule_id": 5,
        "event_start": "2025-01-15T17:00:00+02:00",
        "event_end": "2025-01-16T00:00:00+02:00"
      }
    }
  ]
}
```

## Technical Details

### Precedence Logic
1. **Manual entries** always override rule occurrences on the same date
2. **Exceptions** cancel specific rule occurrences
3. **Rules** fill in remaining dates not covered by manual entries

### Timezone Handling
- All date/time calculations use `Asia/Jerusalem` timezone
- Database stores `timestamptz` (UTC with timezone info)
- UI displays in local time
- Prevents "day shift" bugs around DST transitions

### Pattern Details

**Weekly:**
- Occurs every week on specified days
- Days: 0=Sunday, 1=Monday, ..., 6=Saturday

**Biweekly:**
- Occurs every other week on specified days
- Uses `anchor_date` as week 0 reference
- Even weeks (0, 2, 4, ...) are active

**Monthly:**
- Occurs on specified day of month (1-31)
- Skips months where day doesn't exist (e.g., Feb 31)

### Database Indexes
- Optimized queries with indexes on:
  - `(org_id, employee_id)` - Fast employee lookup
  - `(org_id, start_date, until_date)` - Fast date range queries
  - `(rule_id)` - Fast exception lookups

## Migration Notes

### Backward Compatibility
- Existing `employee_unavailability` records continue to work
- New `source_type` field defaults to 'manual' for existing data
- No data loss during migration

### Migration Process
1. Migration creates new tables with idempotent DDL (`CREATE TABLE IF NOT EXISTS`)
2. Adds new columns to existing table with safe defaults
3. Backfills existing records with `source_type='manual'`
4. Creates indexes for performance
5. Applies on app startup automatically

## Future Enhancements

Potential additions not implemented in this phase:
- UI "Cancel on this date" button to create exceptions inline
- Visual calendar view of unavailability
- Shift Organizer UI badge showing unavailable employees
- Export/import rules for bulk management
- Notification when rule affects upcoming shifts
- Analytics on most common unavailability patterns

## Files Changed

**New Files:**
- `db/migrations/013_recurring_availability.sql` - Database schema
- `app/services/recurring_availability.py` - Rule expansion logic
- `tests/test_recurring_availability.py` - Test suite

**Modified Files:**
- `app/db_schema.py` - Migration registration
- `app/repositories.py` - New repository classes
- `app/routers/availability.py` - Enhanced API endpoints
- `app/routers/shift_organizer.py` - Conflict detection endpoint
- `app/routers/ui.py` - UI enhancements

## Testing Checklist

✅ Unit tests for rule expansion (weekly/biweekly/monthly)
✅ Edge cases (invalid dates, overlaps)
✅ Timezone handling
✅ Precedence logic (manual > rule)
✅ Exception handling
✅ Event conflict detection
✅ Code review completed
✅ All tests passing

## Deployment Notes

1. Migration runs automatically on app startup
2. No downtime required (backward compatible)
3. Existing data preserved
4. New features immediately available after deployment
5. No configuration changes needed

## Support Information

**Documentation:**
- This file: Implementation summary
- Test file: Usage examples and expected behavior
- Migration SQL: Database schema details

**Troubleshooting:**
- Check logs for migration errors during startup
- Verify timezone settings (`Asia/Jerusalem`)
- Test with known employee/dates before production use

---

**Implementation Date:** 2025-12-27
**Version:** 1.0
**Status:** Complete and Tested ✅
