# app/credentials.py
import os

# Twilio Content Template SIDs
CONTENT_SID_INIT = os.getenv("CONTENT_SID_INIT")
CONTENT_SID_RANGES = os.getenv("CONTENT_SID_RANGES")
CONTENT_SID_HALVES = os.getenv("CONTENT_SID_HALVES")
CONTENT_SID_CONFIRM = os.getenv("CONTENT_SID_CONFIRM")
CONTENT_SID_NOT_SURE = os.getenv("CONTENT_SID_NOT_SURE")
CONTENT_SID_CONTACT = os.getenv("CONTENT_SID_CONTACT")
CONTENT_SID_SHIFT_REMINDER = os.getenv("CONTENT_SID_SHIFT_REMINDER")

# Messaging Service SID (למקרה שהקובץ יידרש לו)
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")

# וולידציה בסיסית כדי לעלות שגיאה ברורה אם חסר משתנה
missing = [
    name
    for name, val in {
        "CONTENT_SID_INIT": CONTENT_SID_INIT,
        "CONTENT_SID_RANGES": CONTENT_SID_RANGES,
        "CONTENT_SID_HALVES": CONTENT_SID_HALVES,
        "CONTENT_SID_CONFIRM": CONTENT_SID_CONFIRM,
        "CONTENT_SID_NOT_SURE": CONTENT_SID_NOT_SURE,
        "CONTENT_SID_CONTACT": CONTENT_SID_CONTACT,
        "CONTENT_SID_SHIFT_REMINDER": CONTENT_SID_SHIFT_REMINDER,
    }.items()
    if not val
]

if missing:
    raise RuntimeError(
        f"Missing required env vars: {', '.join(missing)}. "
        "Set them in Render > Environment."
    )
