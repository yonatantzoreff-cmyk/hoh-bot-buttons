# Skip Reporting Implementation Summary

## Problem Statement

In POST /api/scheduler/fetch, we scan 44 events but create 0 jobs with 0 errors. This means we are silently skipping everything.

## Solution Implemented

Added detailed skip reporting to track and report why jobs are being skipped during the fetch operation.

## Changes Made

### 1. Updated Response Model (`FetchResponse`)

Added three new fields to the response:
- `jobs_skipped: int` - Count of skipped jobs
- `skipped_reasons: dict[str, int]` - Breakdown of skip reasons with counts
- `skipped_samples: list[dict]` - First 10 skipped jobs with event details

### 2. Enhanced Job Builder Functions

#### `build_or_update_jobs_for_event()`
Now tracks and returns skip reasons:
- `missing_event_id` - Event not found in database
- `missing_event_date` - Event has no event_date field
- `already_up_to_date` - Job exists and send_at hasn't changed
- `already_sent_or_failed` - Job exists but in terminal state
- `disabled_by_settings` - Message type disabled in settings

**Important**: For INIT/TECH_REMINDER jobs with missing phone, we **still create a scheduled_messages row** with:
- `status='blocked'`
- `last_error='Missing recipient phone'`
- `event_id` set correctly

This ensures blocked jobs appear in the UI as "חסר" (missing).

#### `build_or_update_jobs_for_shifts()`
Similarly tracks skip reasons:
- `missing_required_time_fields` - Shift has no call_time
- `missing_event_id` - Event ID is null
- `already_up_to_date` - Job exists and send_at hasn't changed
- `already_sent_or_failed` - Job exists but in terminal state
- `disabled_by_settings` - Shift reminders disabled

### 3. Updated Fetch Endpoint

The `/api/scheduler/fetch` endpoint now:
1. Collects skip information from job builder functions
2. Aggregates skip counts by reason across all events
3. Collects samples of skipped jobs (first 10) with details
4. Returns comprehensive statistics in the response

### Example Response

```json
{
  "success": true,
  "message": "Synced 44 events and 0 shifts",
  "events_scanned": 44,
  "shifts_scanned": 0,
  "jobs_created": 5,
  "jobs_updated": 12,
  "jobs_blocked": 8,
  "jobs_skipped": 67,
  "skipped_reasons": {
    "disabled_by_settings": 44,
    "already_up_to_date": 15,
    "already_sent_or_failed": 8
  },
  "skipped_samples": [
    {
      "event_id": 123,
      "event_name": "Concert at Park",
      "message_type": "TECH_REMINDER",
      "reason": "disabled_by_settings"
    },
    {
      "event_id": 124,
      "event_name": "Festival Opening",
      "message_type": "INIT",
      "reason": "already_up_to_date"
    }
  ],
  "errors_count": 0,
  "errors": []
}
```

## Skip Reasons Reference

| Reason | Description | Action Taken |
|--------|-------------|--------------|
| `missing_event_id` | Event not found in database | Skips job creation |
| `missing_event_date` | Event has no event_date | Skips job creation |
| `missing_required_time_fields` | Shift has no call_time | Skips job creation |
| `already_up_to_date` | Job exists and send_at hasn't changed | Skips update |
| `already_sent_or_failed` | Job exists in terminal state | Skips update |
| `disabled_by_settings` | Message type disabled in org settings | Skips job creation |

**Note**: Missing recipient phone does NOT create a skip. Instead, it creates a **BLOCKED job** with `status='blocked'` and `last_error='Missing recipient phone'` so it appears in the UI.

## Testing

### Automated Tests

Added two new test cases in `tests/test_scheduler_fetch.py`:

1. **`test_fetch_endpoint_tracks_skip_reasons`**
   - Verifies skip reasons are tracked and reported
   - Tests disabled settings scenario
   - Validates skipped_reasons and skipped_samples fields

2. **`test_fetch_endpoint_creates_blocked_jobs_for_missing_phone`**
   - **Critical test**: Ensures missing phone creates BLOCKED job, not skip
   - Verifies `scheduled_messages` row is created
   - Validates `status='blocked'` and error message

### Manual Verification

Created comprehensive test scenarios demonstrating:
- ✓ Missing phones → BLOCKED jobs (appear in UI as 'חסר')
- ✓ Disabled settings → SKIPPED jobs
- ✓ Already up-to-date → SKIPPED jobs
- ✓ Skip reasons tracked and reported
- ✓ Skip samples provided for debugging

All tests pass successfully.

## Impact

### Before
- Scanning 44 events, creating 0 jobs, with no visibility into why
- Silent failures - no way to debug skip reasons
- Users confused about why jobs aren't being created

### After
- Clear reporting: "Synced 44 events, 67 skipped"
- Detailed breakdown: "67 skipped: 44 disabled_by_settings, 15 already_up_to_date, 8 already_sent_or_failed"
- Sample events for debugging: "Event 123 'Concert at Park' TECH_REMINDER skipped: disabled_by_settings"
- **Critical fix**: Missing phones now create blocked jobs that appear in UI, not silently skipped

## Files Modified

1. `app/routers/scheduler.py` - Added skip tracking to FetchResponse and fetch endpoint
2. `app/services/scheduler_job_builder.py` - Enhanced job builders to track skip reasons
3. `tests/test_scheduler_fetch.py` - Added comprehensive tests for skip reporting

## Backward Compatibility

The changes are fully backward compatible:
- Existing fields in `FetchResponse` remain unchanged
- New fields have default values (empty dict/list)
- Existing API consumers will continue to work without changes
- New fields are optional additions for enhanced debugging
