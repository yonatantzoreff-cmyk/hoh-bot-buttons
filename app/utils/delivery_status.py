"""Delivery status normalization helpers.

All provider statuses are mapped to a canonical subset the app expects for
reporting: ``queued``, ``sent``, ``delivered``, or ``failed``.
"""
from __future__ import annotations

from typing import Optional

_CANONICAL_STATUSES = {"queued", "sent", "delivered", "failed"}


def normalize_delivery_status(status: Optional[str]) -> str:
    """Normalize provider-specific status strings into canonical values.

    Unknown or empty statuses default to ``queued`` when they look like a
    pre-send state, and to ``failed`` when they look like an error. Any
    unrecognized success state falls back to ``sent`` so the UI consistently
    shows progress through the expected lifecycle.
    """

    if not status:
        return "queued"

    status_lower = status.strip().lower()
    mapping = {
        "accepted": "queued",
        "queued": "queued",
        "pending": "queued",
        "sending": "sent",
        "sent": "sent",
        "submitted": "sent",
        "delivered": "delivered",
        "read": "delivered",  # WhatsApp sometimes reports "read"
        "undelivered": "failed",
        "failed": "failed",
        "canceled": "failed",
        "cancelled": "failed",
        "error": "failed",
    }

    if status_lower in mapping:
        return mapping[status_lower]

    if "fail" in status_lower or "error" in status_lower or "cancel" in status_lower:
        return "failed"

    if status_lower in _CANONICAL_STATUSES:
        return status_lower

    return "sent"
