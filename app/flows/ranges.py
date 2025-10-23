"""Utilities for sending range and half-hour selection templates."""

from __future__ import annotations

import logging
import os
from typing import Dict, List

from app.twilio_client import send_content_message

logger = logging.getLogger(__name__)

CONTENT_SID_RANGES = os.getenv("CONTENT_SID_RANGES")
CONTENT_SID_HALVES = os.getenv("CONTENT_SID_HALVES")

if not CONTENT_SID_RANGES or not CONTENT_SID_HALVES:
    logger.warning("Missing CONTENT_SID_RANGES or CONTENT_SID_HALVES env vars")

# Mapping of range IDs to display labels (2-hour intervals)
RANGE_LABELS: List[tuple[str, str]] = [
    ("SLOT_06_08", "06–08"),
    ("SLOT_08_10", "08–10"),
    ("SLOT_10_12", "10–12"),
    ("SLOT_12_14", "12–14"),
    ("SLOT_14_16", "14–16"),
    ("SLOT_16_18", "16–18"),
    ("SLOT_18_20", "18–20"),
]

# Mapping of range IDs to (start_time, end_time)
RANGE_ID_TO_BOUNDS: Dict[str, tuple[str, str]] = {
    "SLOT_06_08": ("06:00", "08:00"),
    "SLOT_08_10": ("08:00", "10:00"),
    "SLOT_10_12": ("10:00", "12:00"),
    "SLOT_12_14": ("12:00", "14:00"),
    "SLOT_14_16": ("14:00", "16:00"),
    "SLOT_16_18": ("16:00", "18:00"),
    "SLOT_18_20": ("18:00", "20:00"),
}


def send_ranges(to_number: str) -> None:
    """Send a list picker with 2-hour ranges to the user."""
    if not CONTENT_SID_RANGES:
        logger.warning("Cannot send ranges – CONTENT_SID_RANGES is missing")
        return

    vars_map = {f"slot{i + 1}": label for i, (_, label) in enumerate(RANGE_LABELS)}
    send_content_message(to_number, CONTENT_SID_RANGES, vars_map)


def half_hour_slots_for_range(range_id: str) -> List[str]:
    """Return half-hour slots for the given 2-hour range id."""
    if range_id not in RANGE_ID_TO_BOUNDS:
        raise KeyError(f"Unknown range id: {range_id}")

    start, end = RANGE_ID_TO_BOUNDS[range_id]
    start_hour, start_minute = map(int, start.split(":"))
    end_hour, end_minute = map(int, end.split(":"))

    slots: List[str] = []
    hour, minute = start_hour, start_minute
    while (hour < end_hour) or (hour == end_hour and minute <= end_minute):
        slots.append(f"{hour:02d}:{minute:02d}")
        minute += 30
        if minute == 60:
            minute = 0
            hour += 1
    return slots


def send_halves(to_number: str, range_id: str) -> None:
    """Send a list picker with half-hour slots within the selected range."""
    if not CONTENT_SID_HALVES:
        logger.warning("Cannot send half-hour slots – CONTENT_SID_HALVES is missing")
        return

    times = half_hour_slots_for_range(range_id)
    vars_map = {f"t{i + 1}": t for i, t in enumerate(times)}
    send_content_message(to_number, CONTENT_SID_HALVES, vars_map)
