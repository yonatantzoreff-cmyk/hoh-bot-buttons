from app.twilio_client import send_content_message

# ב-Render הגדרת כבר Content SIDs:
# hoh_ranges  -> טווחי שעתיים (List Picker ראשי)
# hoh_ranges_halves -> חצאי שעות אחרי בחירת טווח
# ודא ששמרת אותם כ-ENV (או בתוך credentials.py אם אתה טוען אותם משם)

from os import getenv

CONTENT_SID_RANGES = getenv("CONTENT_SID_RANGES")           # לדוגמה: HXxxxxxxxx...
CONTENT_SID_HALVES = getenv("CONTENT_SID_HALVES")           # לדוגמה: HXyyyyyyyy...

def send_ranges(to_number: str):
    """
    שולח למשתמש List Picker של טווחי שעתיים:
    6-8, 8-10, ..., 18-20
    הערה: את התוויות בפועל מגדירים בטמפלייט ב-Twilio Content.
    כאן אנחנו שולחים רק variables אם צריך.
    """
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
    שולח List Picker עם חצאי שעות בין start_hour ל-end_hour (כולל קצה שמאלי).
    לדוגמה לטווח 6-8 יישלח: 06:00, 06:30, 07:00, 07:30, 08:00
    הערה: את התוויות וה-value (slot_HH_MM) מגדירים בטמפלייט hoh_ranges_halves.
    כאן אפשר, אם צריך, להזרים כיתובים שונים באמצעות variables.
    """
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
