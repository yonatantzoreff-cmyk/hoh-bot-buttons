"""Helpers for parsing Twilio interactive action identifiers.

All interactive button/list IDs must embed the event id so that we never
guess which event a producer is talking about based on phone number alone.
"""

from __future__ import annotations

import re
from typing import Optional, TypedDict


class ParsedAction(TypedDict, total=False):
    type: str
    event_id: int
    range_id: int
    half_index: int


ACTION_PATTERNS = [
    (re.compile(r"^CHOOSE_TIME_EVT_(\d+)$"), "CHOOSE_TIME"),
    (re.compile(r"^NOT_SURE_EVT_(\d+)$"), "NOT_SURE"),
    (re.compile(r"^NOT_CONTACT_EVT_(\d+)$"), "NOT_CONTACT"),
    (re.compile(r"^RANGE_(\d+)_EVT_(\d+)$"), "RANGE"),
    (re.compile(r"^HALF_(\d+)_EVT_(\d+)_RANGE_(\d+)$"), "HALF"),
    (re.compile(r"^BACK_TO_RANGES_EVT_(\d+)$"), "BACK_TO_RANGES"),
    (re.compile(r"^BACK_TO_INIT_EVT_(\d+)$"), "BACK_TO_INIT"),
    (re.compile(r"^CONFIRM_SLOT_EVT_(\d+)$"), "CONFIRM_SLOT"),
    (re.compile(r"^CHANGE_SLOT_EVT_(\d+)$"), "CHANGE_SLOT"),
]


def parse_action_id(action_id: str) -> Optional[ParsedAction]:
    for pattern, action_type in ACTION_PATTERNS:
        match = pattern.match(action_id)
        if not match:
            continue

        if action_type == "RANGE":
            range_id = int(match.group(1))
            event_id = int(match.group(2))
            return {"type": action_type, "range_id": range_id, "event_id": event_id}

        if action_type == "HALF":
            half_index = int(match.group(1))
            event_id = int(match.group(2))
            range_id = int(match.group(3))
            return {
                "type": action_type,
                "half_index": half_index,
                "event_id": event_id,
                "range_id": range_id,
            }

        event_id = int(match.group(1))
        return {"type": action_type, "event_id": event_id}

    return None
