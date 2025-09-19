# HOH BOT — Buttons MVP (v2)

Flow: Opening (approved Utility) -> List Picker (in-session) -> Confirm (in-session) -> write to Sheets.

ENV (Render):
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
- TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_FROM
- CONTENT_SID_INIT_QR (approved), CONTENT_SID_SLOT_LIST
- Optional: CONTENT_SID_CONFIRM_QR, CONTENT_SID_NOT_SURE_QR, CONTENT_SID_CONTACT_QR
- GOOGLE_CREDENTIALS_FILE or GOOGLE_CREDENTIALS_B64
- SHEET_EVENTS_NAME, SHEET_MESSAGES_NAME, [SPREADSHEET_KEY], TZ

Endpoints:
- POST /whatsapp-webhook
- POST /run_followups
- GET  /health

UI (MVP)
- /ui → Add a new event
- /ui/events → Manage events & send INIT manually

## UI (MVP) — Manage Events
- `/ui` — Add a new event
- `/ui/events` — View & manage all events
  - **Send INIT** — Manually trigger INIT to the contact of that event
  - **Edit** — Update event name/date/time/contact/phone in the Events sheet
  - **Delete** — Cascade delete this event from:
    - Events
    - ContactsReferrals
    - ContactsVault: remove the event_id from `event_ids_json` arrays
  - Deletion does not recall messages already sent.
