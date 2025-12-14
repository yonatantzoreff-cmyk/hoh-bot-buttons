# HOH BOT — Buttons MVP (v2)

Flow: Opening (approved Utility) -> List Picker (in-session) -> Confirm (in-session) -> **persist and drive logic from Postgres** (events, contacts, conversations, messages). Google Sheets is no longer part of the runtime, and legacy sheet artifacts have been removed.

ENV (Render):
- DATABASE_URL
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
- TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_FROM
- CONTENT_SID_INIT_QR (approved), CONTENT_SID_SLOT_LIST
- Optional: CONTENT_SID_CONFIRM_QR, CONTENT_SID_NOT_SURE_QR, CONTENT_SID_CONTACT_QR

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
  - **Edit/Delete** — Manage events directly in Postgres (events, contacts, conversations, messages)
