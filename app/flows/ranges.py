import os
from app.credentials import CONTENT_SID_RANGES, CONTENT_SID_HALVES

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
# ב-Render הגדרת כבר Content SIDs:
# hoh_ranges  -> טווחי שעתיים (List Picker ראשי)
# hoh_ranges_halves -> חצאי שעות אחרי בחירת טווח
# ודא ששמרת אותם כ-ENV (או בתוך credentials.py אם אתה טוען אותם משם)

def send_ranges(to_number: str):
    """
    Send a list picker with 2-hour ranges to the user.
    The template must have variables slot1..slot7 matching the number of items.
    """
    vars_map = {f"slot{i+1}": label for i, (_, label) in enumerate(RANGE_LABELS)}
    send_content_message(to_number, CONTENT_SID_RANGES, vars_map)
from os import getenv

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
CONTENT_SID_RANGES = getenv("CONTENT_SID_RANGES")           # לדוגמה: HXxxxxxxxx...
CONTENT_SID_HALVES = getenv("CONTENT_SID_HALVES")           # לדוגמה: HXyyyyyyyy...

def half_hour_slots_for_range(range_id: str) -> list[str]:
def send_ranges(to_number: str):
"""
    Given a range ID, returns a list of time strings in 30-minute increments.
    Includes the end time as well.
    שולח למשתמש List Picker של טווחי שעתיים:
    6-8, 8-10, ..., 18-20
    הערה: את התוויות בפועל מגדירים בטמפלייט ב-Twilio Content.
    כאן אנחנו שולחים רק variables אם צריך.
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
    # אם הטמפלייט לא דורש variables — שלח ריק.
    variables = {}
    # אם הטמפלייט כן צריך טקסטים/IDs, אפשר לשלוח map.
    # מומלץ שב-Twilio תגדיר value עבור כל Item ל-range_{start}_{end} כדי שנתפוס בוובּהוק.

    send_content_message(
        to=to_number,
        content_sid=CONTENT_SID_RANGES,
        variables=variables
    )

def send_halves(to_number: str, start_hour: int, end_hour: int):
"""
    Send a list picker with half-hour slots within the selected range.
    The template must have variables t1..t5 (or more if expanded).
    שולח List Picker עם חצאי שעות בין start_hour ל-end_hour (כולל קצה שמאלי).
    לדוגמה לטווח 6-8 יישלח: 06:00, 06:30, 07:00, 07:30, 08:00
    הערה: את התוויות וה-value (slot_HH_MM) מגדירים בטמפלייט hoh_ranges_halves.
    כאן אפשר, אם צריך, להזרים כיתובים שונים באמצעות variables.
   """
    times = half_hour_slots_for_range(range_id)
    vars_map = {f"t{i+1}": t for i, t in enumerate(times[:5])}
    send_content_message(to_number, CONTENT_SID_HALVES, vars_map)
    # דוגמה לבניית מחרוזות אם הטמפלייט שלך מקבל משתנים item1..itemN:
    # אבל אם כבר בנית את רשימת הפריטים בתוך הטמפלייט ב-Twilio עם values קבועים — אפשר לשלוח {}.
    variables = {
        # רק אם הטמפלייט דורש תוויות/כותרת דינמית
        # "title": f"בחר שעה בין {start_hour:02d}:00 ל-{end_hour:02d}:00"
    }

    send_content_message(
        to=to_number,
        content_sid=CONTENT_SID_HALVES,
        variables=variables
    )
