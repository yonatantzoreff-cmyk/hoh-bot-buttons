"""Utilities for sending range and half-hour selection templates."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List

from app.twilio_client import send_content_message

logger = logging.getLogger(__name__)

CONTENT_SID_RANGES = os.getenv("CONTENT_SID_RANGES")
CONTENT_SID_HALVES = os.getenv("CONTENT_SID_HALVES")

if not CONTENT_SID_RANGES or not CONTENT_SID_HALVES:
    logger.warning("Missing CONTENT_SID_RANGES or CONTENT_SID_HALVES env vars")

RANGE_BOUNDS: Dict[int, tuple[int, int]] = {
    1: (0, 4),
    2: (4, 8),
    3: (8, 12),
    4: (12, 16),
    5: (16, 20),
    6: (20, 24),
}


def send_ranges(to_number: str) -> None:
    """Send a list picker with six 4-hour ranges to the user."""
    if not CONTENT_SID_RANGES:
        logger.warning("Cannot send ranges – CONTENT_SID_RANGES is missing")
        return

    labels = [f"{start:02d}:00–{end:02d}:00" for start, end in RANGE_BOUNDS.values()]
    vars_map = {f"range{i + 1}": label for i, label in enumerate(labels)}
    vars_map["event_id"] = ""
    send_content_message(to_number, CONTENT_SID_RANGES, vars_map)


def half_hour_slots_for_range(range_id: int) -> List[str]:
    """Return 8 half-hour slots for the given 4-hour range id."""
    if range_id not in RANGE_BOUNDS:
        raise KeyError(f"Unknown range id: {range_id}")

    start_hour, _ = RANGE_BOUNDS[range_id]
    start_dt = datetime(2000, 1, 1, start_hour, 0)
    return [
        (start_dt + timedelta(minutes=30 * i)).strftime("%H:%M")
        for i in range(8)
    ]


def send_halves(to_number: str, range_id: int) -> None:
    """Send a list picker with half-hour slots within the selected range."""
    if not CONTENT_SID_HALVES:
        logger.warning("Cannot send half-hour slots – CONTENT_SID_HALVES is missing")
        return

    times = half_hour_slots_for_range(range_id)
    vars_map = {f"h{i + 1}": t for i, t in enumerate(times)}
    vars_map.update({"event_id": "", "range_id": str(range_id)})
    send_content_message(to_number, CONTENT_SID_HALVES, vars_map)
