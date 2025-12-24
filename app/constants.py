"""Shared application constants for statuses and labels."""

from __future__ import annotations

# Centralized list of all event statuses used across the system.
# Order is operational: draft -> pending -> contact checks -> follow-ups -> final.
EVENT_STATUS_OPTIONS: list[str] = [
    "draft",
    "pending",
    "pending_contact",
    "contact_required",
    "waiting_for_reply",
    "open",
    "follow_up",
    "confirmed",
    "cancelled",
]


# Human-friendly Hebrew labels for UI rendering (fallbacks to the raw status).
EVENT_STATUS_LABELS: dict[str, str] = {
    "draft": "טיוטה",
    "pending": "ממתין",
    "pending_contact": "ממתין לאיש קשר",
    "contact_required": "צריך איש קשר",
    "waiting_for_reply": "ממתין לתשובה",
    "open": "פתוח",
    "follow_up": "במעקב",
    "confirmed": "מאושר",
    "cancelled": "בוטל",
}


# Optional mapping for Bootstrap badge variants when needed in the UI.
EVENT_STATUS_BADGE_VARIANTS: dict[str, str] = {
    "draft": "secondary",
    "pending": "warning",
    "pending_contact": "info",
    "contact_required": "info",
    "waiting_for_reply": "warning",
    "open": "primary",
    "follow_up": "info",
    "confirmed": "success",
    "cancelled": "danger",
}
