# app/credentials.py
import os

# Twilio Content Template SIDs
CONTENT_SID_RANGES = os.getenv("CONTENT_SID_RANGES")
CONTENT_SID_HALVES = os.getenv("CONTENT_SID_HALVES")

# Messaging Service SID (למקרה שהקובץ יידרש לו)
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")

# וולידציה בסיסית כדי לעלות שגיאה ברורה אם חסר משתנה
missing = [name for name, val in {
    "CONTENT_SID_RANGES": CONTENT_SID_RANGES,
    "CONTENT_SID_HALVES": CONTENT_SID_HALVES,
    # השורה הבאה לא חובה אם אינך משתמש ישירות במשתנה בכל מודול
    # "TWILIO_MESSAGING_SERVICE_SID": TWILIO_MESSAGING_SERVICE_SID,
}.items() if not val]

if missing:
    raise RuntimeError(
        f"Missing required env vars: {', '.join(missing)}. "
        "Set them in Render > Environment."
    )
