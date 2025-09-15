import os
import json
import logging
from twilio.rest import Client

# --- Env ---
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
# ודא שהמשתנה הזה קיים ב-Render:
MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")

if not ACCOUNT_SID or not AUTH_TOKEN:
    raise RuntimeError("Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN")

client = Client(ACCOUNT_SID, AUTH_TOKEN)


def _normalize_to(to_value: str, channel: str = "whatsapp") -> str:
    """
    מחזיר יעד בפורמט שה-Twilio API מצפה לו, למשל: 'whatsapp:+9725...'
    מקבל גם '+9725...' או כבר 'whatsapp:+9725...'
    """
    if not to_value:
        raise ValueError("Destination number is empty")
    to_value = to_value.strip()
    prefix = f"{channel}:"
    if to_value.startswith(prefix):
        return to_value
    if to_value.startswith("+"):
        return prefix + to_value
    # אם מגיע בלי '+' (לא מומלץ), נוסיף רק את הפרפיקס
    return prefix + to_value


def _to_content_vars(variables):
    """
    Twilio דורש string JSON בשדה content_variables.
    מקבל dict או str ומחזיר str.
    """
    if variables is None:
        return None
    if isinstance(variables, str):
        return variables
    return json.dumps(variables, ensure_ascii=False)


def send_content_message(
    *,
    to: str | None = None,
    to_number: str | None = None,
    content_sid: str,
    variables=None,
    messaging_service_sid: str | None = None,
    channel: str = "whatsapp",
):
    """
    שולח הודעת WhatsApp באמצעות Messaging Service + Content Template.

    פרמטרי יעד:
      - אפשר לשלוח או with `to=` או with `to_number=`
    """
    dest = to or to_number
    if not dest:
        raise TypeError("send_content_message requires 'to' or 'to_number'")

    ms_sid = messaging_service_sid or MESSAGING_SERVICE_SID
    if not ms_sid:
        raise RuntimeError("Missing TWILIO_MESSAGING_SERVICE_SID env var")

    payload = {
        "to": _normalize_to(dest, channel=channel),
        "content_sid": content_sid,
        "content_variables": _to_content_vars(variables),
        "messaging_service_sid": ms_sid,
    }

    logging.info("Twilio content payload: %s", payload)
    return client.messages.create(**payload)
