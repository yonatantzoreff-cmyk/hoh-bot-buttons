from datetime import datetime, time, timedelta
from typing import List
from zoneinfo import ZoneInfo

def generate_half_hour_slots(start: time, end: time, tz: str = "Asia/Jerusalem") -> List[str]:
    """Generate half-hour time slots between start and end times."""
    tzinfo = ZoneInfo(tz)
    today = datetime.now(tzinfo).date()
    # Create timezone-aware datetimes
    cur = datetime.combine(today, start, tzinfo=tzinfo)
    end_dt = datetime.combine(today, end, tzinfo=tzinfo)
    out = []
    while cur <= end_dt:
        out.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=30)
    return out

RANGES = {
    "morning": (time(6,0), time(12,0)),
    "noon": (time(12,0), time(16,0)),
    "afternoon": (time(16,0), time(20,0)),
    "night": (time(20,0), time(23,59)),
}

def slots_for_range(range_key: str, tz: str = "Asia/Jerusalem") -> List[str]:
    if range_key not in RANGES:
        range_key = "noon"
    start, end = RANGES[range_key]
    return generate_half_hour_slots(start, end, tz=tz)[:10]
