# Scheduler Fetch & Cleanup - Implementation Summary

## Overview

This implementation adds the ability to synchronize future events into the scheduler and cleanup old logs, as requested in the problem statement.

## Features Implemented

### 1. Database Changes

**Migration: 010_scheduled_messages_unique_constraints.sql**
- Added unique index `idx_scheduled_messages_unique_event_job` for event-based jobs (INIT, TECH_REMINDER)
  - Constraint: `(org_id, message_type, event_id)` WHERE `shift_id IS NULL`
- Added unique index `idx_scheduled_messages_unique_shift_job` for shift-based jobs (SHIFT_REMINDER)
  - Constraint: `(org_id, message_type, shift_id)` WHERE `shift_id IS NOT NULL`
- These constraints ensure idempotency - running fetch multiple times won't create duplicate jobs

### 2. Backend API Endpoints

#### POST /api/scheduler/fetch
**Purpose:** Synchronize all future events into scheduled_messages

**Behavior:**
1. Queries all events where `event_date >= today` (in Asia/Jerusalem timezone)
2. For each event:
   - Calls `build_or_update_jobs_for_event(event_id)` to create/update INIT + TECH_REMINDER jobs
   - Calls `build_or_update_jobs_for_shifts(event_id)` to create/update SHIFT_REMINDER jobs
3. Respects scheduler settings (enabled_global, enabled_init, enabled_tech, enabled_shift)
4. Recomputes `send_at` for all future jobs based on current settings
5. Validates phone numbers and sets status=blocked if missing

**Response:**
```json
{
  "success": true,
  "message": "Synced X events and Y shifts",
  "events_scanned": 10,
  "shifts_scanned": 25,
  "jobs_created": 15,
  "jobs_updated": 8,
  "jobs_blocked": 2
}
```

**Idempotency:** Running fetch multiple times:
- Creates jobs if they don't exist
- Updates send_at if job exists and is not sent/failed
- Does not duplicate jobs (enforced by unique constraints)

#### DELETE /api/scheduler/past-logs
**Purpose:** Cleanup old completed logs

**Behavior:**
- Deletes `scheduled_messages` WHERE:
  - `status IN ('sent', 'failed', 'skipped')`
  - AND `send_at < now - {days} days` (default: 30 days)
- Does NOT delete:
  - Future scheduled jobs
  - Jobs in 'scheduled', 'retrying', or 'blocked' status

**Parameters:**
- `org_id` (query param, default: 1)
- `days` (query param, default: 30)

**Response:**
```json
{
  "success": true,
  "message": "Deleted 42 old log entries",
  "deleted_count": 42
}
```

#### GET /api/scheduler/jobs (Updated)
**New Parameter:** `show_past` (boolean, default: false)

**Behavior:**
- When `show_past=false` (default):
  - Filters out jobs where `send_at < now` OR `status IN ('sent', 'failed', 'skipped')`
  - Shows only upcoming/active jobs
- When `show_past=true`:
  - Shows all jobs including past/completed ones

### 3. Repository Changes

**EventRepository.list_future_events_for_org(org_id)**
- New method to query only future events
- Filters: `event_date >= today` (in Israel timezone)
- Orders by: `event_date ASC, event_id ASC`

### 4. UI Changes

#### Action Buttons (Top of Scheduler Page)
```html
🔄 Fetch Future Events   |   🗑️ Cleanup Old Logs
```

**Fetch Button:**
- Calls `POST /api/scheduler/fetch`
- Shows spinner while loading
- Displays success alert with counts
- Reloads all job tables

**Cleanup Button:**
- Shows confirmation dialog before deleting
- Calls `DELETE /api/scheduler/past-logs?days=30`
- Shows success alert with deleted count
- Reloads all job tables

#### Show Past Toggle (Each Tab)
```
☐ Hide sent   ☐ Show past
```

**Show Past Checkbox:**
- Controls `show_past` query parameter
- Default: unchecked (past jobs hidden)
- When checked: shows all jobs including completed/past ones

#### Empty State Improvements
When no jobs exist:
```
אין אירועים עתידיים. לחץ "Fetch Future Events" כדי לסנכרן.
(No future events. Click "Fetch Future Events" to sync.)
```

## Technical Details

### Idempotency Implementation

The unique constraints ensure that:
1. Only one INIT job per event
2. Only one TECH_REMINDER job per event
3. Only one SHIFT_REMINDER job per shift

When `build_or_update_jobs_for_event` is called:
- If job exists with status 'scheduled' or 'retrying': updates send_at
- If job exists with status 'sent' or 'failed': does nothing
- If job doesn't exist: creates new job

### Weekend Restriction

**IMPORTANT:** Weekend restriction ONLY applies to INIT messages
- INIT: `apply_weekend_rule=True` in `compute_send_at()`
- TECH_REMINDER: `apply_weekend_rule=False`
- SHIFT_REMINDER: `apply_weekend_rule=False`

This is preserved from the original implementation and verified by tests.

### Phone Validation

Jobs are set to `status=blocked` when:
- INIT: No valid producer phone OR technical phone
- TECH_REMINDER: No valid technical phone
- SHIFT_REMINDER: No valid employee phone

Blocked jobs are not sent but are included in the counts returned by fetch.

## Testing

### Unit Tests (test_scheduler_fetch.py)

1. **test_fetch_endpoint_creates_jobs_for_future_events**
   - Verifies jobs are created for future events
   - Checks that correct counts are returned

2. **test_fetch_endpoint_updates_existing_jobs**
   - Verifies idempotency (updates instead of duplicates)
   - Checks that existing jobs are updated

3. **test_cleanup_endpoint_deletes_old_completed_logs**
   - Verifies only old completed logs are deleted
   - Checks correct SQL query is used

4. **test_show_past_parameter_filters_correctly**
   - Verifies show_past parameter works
   - Tests both show_past=true and false

5. **test_fetch_endpoint_requires_valid_org_id**
   - Verifies graceful handling of invalid org_id

6. **test_cleanup_endpoint_validates_days_parameter**
   - Verifies days parameter is accepted

### Regression Tests

Ran existing tests to ensure no breakage:
- ✅ test_scheduler_job_builder.py (11 tests passed)
- ✅ test_compute_send_at.py (13 tests passed)
- ✅ Verified weekend restriction still only affects INIT

## Usage

### Syncing Future Events

1. Navigate to `/ui/scheduler`
2. Click "🔄 Fetch Future Events" button
3. View results dialog showing counts
4. Jobs appear in respective tabs

### Cleaning Old Logs

1. Navigate to `/ui/scheduler`
2. Click "🗑️ Cleanup Old Logs" button
3. Confirm deletion in dialog
4. View results showing deleted count

### Viewing Past Jobs

1. Navigate to any scheduler tab (INIT/TECH/SHIFT)
2. Check "☑ Show past" checkbox
3. Past/completed jobs will appear in the table

## Files Changed

### Backend
- `db/migrations/010_scheduled_messages_unique_constraints.sql` (NEW)
- `app/db_schema.py` (MODIFIED)
- `app/repositories.py` (MODIFIED)
- `app/routers/scheduler.py` (MODIFIED)

### Frontend
- `app/routers/ui.py` (MODIFIED)

### Tests
- `tests/test_scheduler_fetch.py` (NEW)

## Next Steps

For production deployment:
1. Run database migration to add unique constraints
2. Test fetch functionality with real data
3. Monitor for any conflicts with existing jobs
4. Adjust cleanup days parameter if needed (currently 30 days)

## Security Considerations

- All endpoints use same auth mechanism as existing scheduler endpoints
- No internal token required (uses session-based auth)
- Cleanup operation is safe - only removes completed old jobs
- Fetch operation respects scheduler settings (enabled flags)
