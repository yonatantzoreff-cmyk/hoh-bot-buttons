# HOH BOT — Buttons MVP (v2)

Flow: Opening (approved Utility) -> List Picker (in-session) -> Confirm (in-session) -> **persist and drive logic from Postgres** (events, contacts, conversations, messages). Google Sheets is no longer part of the runtime, and legacy sheet artifacts have been removed.

ENV (Render):
- DATABASE_URL
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
- TWILIO_MESSAGING_SERVICE_SID (required for WhatsApp template sends)
- CONTENT_SID_INIT_QR (approved), CONTENT_SID_SLOT_LIST
- CONTENT_SID_SHIFT_REMINDER (WhatsApp template for employee reminders)
- Optional: CONTENT_SID_CONFIRM_QR, CONTENT_SID_NOT_SURE_QR, CONTENT_SID_CONTACT_QR

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
