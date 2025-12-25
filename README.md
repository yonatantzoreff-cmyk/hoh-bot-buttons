# HOH BOT — Buttons MVP (v2)

Flow: Opening (approved Utility) -> List Picker (in-session) -> Confirm (in-session) -> **persist and drive logic from Postgres** (events, contacts, conversations, messages). Google Sheets is no longer part of the runtime, and legacy sheet artifacts have been removed.

ENV (Render):
- DATABASE_URL
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
- TWILIO_MESSAGING_SERVICE_SID (required for WhatsApp template sends)
- CONTENT_SID_INIT_QR (approved), CONTENT_SID_SLOT_LIST
- CONTENT_SID_SHIFT_REMINDER (WhatsApp template for employee reminders)
- Optional: CONTENT_SID_CONFIRM_QR, CONTENT_SID_NOT_SURE_QR, CONTENT_SID_CONTACT_QR

## Docker Deployment

Build and run locally (or in Render's Docker deploys):

```
docker build -t hohbot .
docker run --rm -p 8000:8000 -e PORT=8000 -e DATABASE_URL="..." hohbot
```

On Render, choose **Deploy: Docker** and set `DATABASE_URL` plus the other secrets as Environment Variables.

## Timezone Handling

The system uses a **centralized timezone approach** to ensure consistent time handling across all components:

### Standards
- **Database**: All timestamps are stored in **UTC** using PostgreSQL's `TIMESTAMPTZ` type
- **UI**: Times are displayed and accepted in **Israel local time** (Asia/Jerusalem)
- **Twilio Messages**: All times in WhatsApp messages are displayed in **Israel local time**
- **DST**: Daylight Saving Time transitions are handled automatically by the `zoneinfo` library

### Key Principles
1. **No manual hour offsets**: Never add or subtract hours manually (e.g., +2, -2)
2. **Always timezone-aware**: All datetime objects should include timezone information
3. **Single source of truth**: Use `app/time_utils.py` for all timezone conversions
4. **DB stores UTC**: Always convert local times to UTC before storing in the database
5. **Display shows local**: Always convert UTC from DB to Israel local time for display

### Example: Adding an Event with Time 21:00
```python
from app.time_utils import parse_local_time_to_utc, utc_to_local_time_str
from datetime import date

# User enters "21:00" in the UI for July 15, 2024
event_date = date(2024, 7, 15)
show_time_str = "21:00"

# Convert to UTC for storage (handles DST automatically)
show_time_utc = parse_local_time_to_utc(event_date, show_time_str)
# Result: 2024-07-15 18:00:00 UTC (21:00 Israel time - 3 hours in summer)

# Store show_time_utc in database...

# Later, when displaying:
display_time = utc_to_local_time_str(show_time_utc)
# Result: "21:00" (back to Israel local time)
```

### Before/After Fix
**Before (Bug):**
- User creates event with time 21:00
- Time stored incorrectly as 21:00 UTC (should have been 19:00 or 18:00 UTC)
- Display shows 23:00 or 00:00 (wrong!)
- Each edit shifted time by 2 hours

**After (Fixed):**
- User creates event with time 21:00
- Time stored correctly as 18:00 UTC (summer) or 19:00 UTC (winter)
- Display always shows 21:00 (correct!)
- Edit operations preserve the exact time

### Testing
Comprehensive timezone tests are in `tests/test_timezone_fixes.py`:
- Round-trip conversions (UI → DB → UI)
- Edit operations don't cause time drift
- DST transitions handled correctly
- Multiple edits don't accumulate errors

Run tests with: `pytest tests/test_timezone_fixes.py -v`

Endpoints:
- POST /whatsapp-webhook
- POST /run_followups
- GET  /health

UI (MVP)
- /ui → Add a new event
- /ui/events → Manage events & send INIT manually
- /ui/calendar-import → Import monthly calendar from Excel

## UI (MVP) — Manage Events
- `/ui` — Add a new event
- `/ui/events` — View & manage all events
  - **Send INIT** — Manually trigger INIT to the contact of that event
  - **Edit/Delete** — Manage events directly in Postgres (events, contacts, conversations, messages)
- `/ui/calendar-import` — Import monthly calendar from Excel
  - **Upload** — Upload Excel file with calendar data
  - **Review & Edit** — Review staging events with validation
  - **Commit** — Commit valid events to official events table

## Calendar Import Feature

The calendar import feature allows admins to bulk-import events from Excel files.

### Excel Format

The Excel file must contain a single sheet with the following Hebrew column headers:

- **תאריך** → date (required)
- **שעה** → show_time (required, 24h format)
- **שם המופע** → name (required)
- **שעה טכני** → load_in (optional, 24h format)
- **סדרה** → event_series (optional)
- **גוף מבצע / איש קשר** → producer_name (optional but recommended)
- **טלפון** → producer_phone (optional)
- **הערות** → notes (optional)
- **יום** → day (informational only, not stored)

### Import Process

1. **Upload**: Navigate to `/ui/calendar-import` and upload an Excel (.xlsx) file
2. **Review**: The system validates all rows and displays them in a staging table:
   - ✅ **Valid** (green): Ready to commit
   - ⚠️ **Warning** (orange): Missing optional fields, but can still be committed
   - ❌ **Invalid** (red): Has errors that must be fixed before commit
3. **Edit**: Click on any staging row to edit fields inline
4. **Validate**: Click "Revalidate All" to re-check all events
5. **Commit**: Click "Commit to Events" to:
   - Create events in the official events table
   - Create contacts for new producer phones (if phone is provided)
   - Handle duplicates (option to skip or continue)
   - Clear all staging data after successful commit

### Validation Rules

**Hard Errors (block commit):**
- Missing or invalid date
- Missing or invalid show time (must be 24h format)
- Empty event name

**Warnings (don't block commit):**
- Missing producer phone
- Missing load-in time
- Missing producer name

**Duplicate Detection:**
- Events with the same date + show_time + name are flagged as potential duplicates
- User can choose to skip duplicates or commit anyway during the commit process

### API Endpoints

Admin-only endpoints for programmatic access:

- `POST /import/upload` — Upload Excel file
- `GET /import/staging` — List all staging events
- `PATCH /import/staging/{id}` — Update a staging event
- `POST /import/staging` — Add a new blank row
- `DELETE /import/staging/{id}` — Delete a staging event
- `POST /import/validate` — Revalidate all staging events
- `POST /import/commit` — Commit valid events to official events table
- `POST /import/clear` — Clear all staging data

### Database Schema

The feature uses the `staging_events` table to temporarily hold imported data before commit:

```sql
CREATE TABLE staging_events (
    id                BIGSERIAL PRIMARY KEY,
    org_id            BIGINT NOT NULL REFERENCES orgs(org_id),
    row_index         INTEGER NOT NULL,
    date              DATE,
    show_time         TIME,
    name              TEXT,
    load_in           TIME,
    event_series      TEXT,
    producer_name     TEXT,
    producer_phone    TEXT,
    notes             TEXT,
    is_valid          BOOLEAN NOT NULL DEFAULT FALSE,
    errors_json       JSONB,
    warnings_json     JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Migration

To enable the calendar import feature, run the migration:

```bash
psql $DATABASE_URL < db/migrations/002_calendar_import.sql
```

On startup the app now checks for the `staging_events` table and will try to
apply the migration if it's missing. If the table still doesn't exist, the
process will fail fast with a clear error so you know to run the command above
against the correct database (the logs include the DB host/name).

## Scheduler Diagnostics

The scheduler diagnostics endpoint helps troubleshoot why scheduled messages may not be visible in the UI/API. It performs comprehensive checks on database connection, schema, data visibility, org scoping, endpoint queries, fetch logic, and timezone configuration.

### Running Diagnostics

**Via API (recommended):**
```bash
curl -H "Authorization: Bearer <SCHEDULER_RUN_TOKEN>" \
     "https://<your-host>/internal/diagnostics/scheduler?org_id=1"
```

**Via CLI (local development):**
```bash
python -m app.diagnostics.scheduler --org-id 1
```

### Authentication

The diagnostics endpoint is protected by the same Bearer token as the scheduler run endpoint. Set the `SCHEDULER_RUN_TOKEN` environment variable:

```bash
export SCHEDULER_RUN_TOKEN="your-secret-token"
```

The endpoint will:
- Return **401** if the token is invalid or missing
- Return **500** if the token is not configured

### Response Structure

The endpoint returns a JSON report with three main sections:

```json
{
  "summary": {
    "suspected_root_cause": "All scheduled jobs are in the past (show_past=false filters them out)",
    "confidence": 85,
    "key_evidence": [
      "5 jobs exist but 0 are future",
      "Status distribution: {'sent': 3, 'scheduled': 2}",
      "Future events available for fetch: 0"
    ],
    "checks_summary": {
      "total": 7,
      "passed": 4,
      "warnings": 3,
      "failed": 0
    }
  },
  "checks": [
    {
      "name": "DB_FINGERPRINT",
      "status": "pass",
      "details": { ... },
      "why_it_matters": "Confirms which database the application is connected to",
      "likely_root_cause": null,
      "next_actions": ["Compare with DBeaver connection settings"]
    },
    ...
  ],
  "recommendations": [
    {
      "priority": "P1",
      "title": "Create events with future dates",
      "description": "All events are in the past. Create events with event_date >= today.",
      "commands": ["Check event_date values", "Create new events or update existing ones"]
    },
    ...
  ]
}
```

### Diagnostic Checks

The diagnostics run the following checks:

1. **DB_FINGERPRINT** — Verifies database connection and reports:
   - Database name, schema, server address/port
   - PostgreSQL version
   - Current timestamp and timezone

2. **SCHEMA_CHECK** — Verifies table existence and structure:
   - scheduled_messages, scheduler_settings, events, employee_shifts
   - Column definitions, data types, constraints
   - Primary keys and enum values

3. **SCHEDULED_MESSAGES_DATA** — Inspects data visibility:
   - Total row counts (future vs past)
   - Distribution by message_type and status
   - Sample of last 10 rows
   - Detection of orphaned rows (missing event_id/shift_id)

4. **ORG_SCOPING_CHECK** — Verifies org_id filtering:
   - Distribution of org_id values in scheduled_messages
   - Distribution of org_id values in events
   - Potential mismatches that would hide data

5. **ENDPOINT_SIMULATION** — Simulates API queries:
   - Reproduces `/api/scheduler/jobs` with different filter combinations
   - Shows how many rows would be returned
   - Explains why rows were excluded

6. **FETCH_DIAGNOSTICS** — Explains why fetch button doesn't import:
   - Counts future events found by fetch query
   - Shows sample events with date fields
   - Detects timezone issues in date filtering

7. **TIMEZONE_CHECK** — Verifies timezone configuration:
   - Database timezone setting
   - Comparison of DB time vs app time
   - Sample send_at timestamps in different timezones

### Common Issues Detected

- **Empty scheduled_messages table** → Fetch button hasn't been clicked
- **All jobs in the past** → show_past=false filter hides them
- **No future events** → All events have past dates
- **Org ID mismatch** → Jobs exist for different org_id than UI requests
- **Database mismatch** → App connected to different DB than DBeaver
- **Missing tables** → Migrations not run
- **Timezone confusion** → UTC/local time mixing

### Troubleshooting Tips

1. **If you see 0 scheduled messages:**
   - Click "Fetch future events" button in UI
   - Check that events with future dates exist

2. **If fetch finds 0 future events:**
   - Verify events table has rows with `event_date >= today` (Israel time)
   - Check timezone configuration matches Asia/Jerusalem

3. **If scheduled messages exist but don't show in UI:**
   - Try `show_past=true` filter
   - Check org_id parameter matches your data
   - Compare DB fingerprint with DBeaver connection

4. **If all tests pass but UI still has issues:**
   - Check browser console for JavaScript errors
   - Verify API endpoint is being called correctly
   - Look at network tab to see actual API responses
