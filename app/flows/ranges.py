import os

CONTENT_SID_RANGES = os.getenv("CONTENT_SID_RANGES")
CONTENT_SID_HALVES = os.getenv("CONTENT_SID_HALVES")

if not CONTENT_SID_RANGES or not CONTENT_SID_HALVES:
    # לא חוסם ריצה אם לא רוצים, אבל עדיף לפחות שיירשם בלוג
    print("⚠️ Missing CONTENT_SID_RANGES or CONTENT_SID_HALVES env vars")

from app.twilio_client import send_content_message

# Mapping of range IDs to display labels (2-hour intervals)
RANGE_LABELS = [
    ("SLOT_06_08", "06–08"),
    ("SLOT_08_10", "08–10"),
    ("SLOT_10_12", "10–12"),
    ("SLOT_12_14", "12–14"),
    ("SLOT_14_16", "14–16"),
    ("SLOT_16_18", "16–18"),
    ("SLOT_18_20", "18–20"),
]

def send_ranges(to_number: str):
    """
    Send a list picker with 2-hour ranges to the user.
    The template must have variables slot1..slot7 matching the number of items.
    """
    vars_map = {f"slot{i+1}": label for i, (_, label) in enumerate(RANGE_LABELS)}
    send_content_message(to_number, CONTENT_SID_RANGES, vars_map)

# Mapping of range IDs to (start_time, end_time)
RANGE_ID_TO_BOUNDS = {
    "SLOT_06_08": ("06:00", "08:00"),
    "SLOT_08_10": ("08:00", "10:00"),
    "SLOT_10_12": ("10:00", "12:00"),
    "SLOT_12_14": ("12:00", "14:00"),
    "SLOT_14_16": ("14:00", "16:00"),
    "SLOT_16_18": ("16:00", "18:00"),
    "SLOT_18_20": ("18:00", "20:00"),
}

def half_hour_slots_for_range(range_id: str) -> list[str]:
    """
    Given a range ID, returns a list of time strings in 30-minute increments.
    Includes the end time as well.
    """
    start, end = RANGE_ID_TO_BOUNDS[range_id]
    h, m = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    slots: list[str] = []
    while (h < eh) or (h == eh and m <= em):
        slots.append(f"{h:02d}:{m:02d}")
        m += 30
        if m == 60:
            m = 0
            h += 1
    return slots

def send_halves(to_number: str, range_id: str):
    """
    Send a list picker with half-hour slots within the selected range.
    The template must have variables t1..t5 (or more if expanded).
    """
    times = half_hour_slots_for_range(range_id)
    vars_map = {f"t{i+1}": t for i, t in enumerate(times[:5])}
    send_content_message(to_number, CONTENT_SID_HALVES, vars_map)
