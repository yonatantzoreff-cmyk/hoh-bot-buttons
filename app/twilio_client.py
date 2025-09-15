# app/twilio_client.py
import os
import json
from typing import Dict, Optional
from twilio.rest import Client

# --- Env & client ---
ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]

# עדיף לעבוד עם Messaging Service
MESSAGING_SERVICE_SID = (
    os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
    or os.environ.get("MESSAGING_SERVICE_SID")
)

# אופציונלי בלבד אם אין Messaging Service
WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # למשל "whatsapp:+15551234567" או "+15551234567"

client = Client(ACCOUNT_SID, AUTH_TOKEN)


def _normalize_to(to_number: str, channel: str = "whatsapp") -> str:
    """
    מחזיר מס' יעד בפורמט תקין לערוץ (ברירת מחדל: WhatsApp).
    קלטים אפשריים: "050...", "+97250...", "whatsapp:+97250..."
    """
    s = to_number.strip()
    if channel == "whatsapp":
        if s.startswith("whatsapp:"):
            return s
        if s.startswith("+"):
            return f"whatsapp:{s}"
        # הוספת קידומת בינלאומית אם חסרה
        if s.startswith("0"):
            # ישראל כברירת מחדל: 0XXXXXXXXX -> +972XXXXXXXXX
            s = "+972" + s[1:]
        elif s.startswith("972"):
            s = "+" + s
        return f"whatsapp:{s}"
    return s


def _resolve_from_for_whatsapp() -> Optional[str]:
    """
    קובע את שדה ה-from במקרה שאין Messaging Service.
    מחזיר מחרוזת בפורמט "whatsapp:+1..." או None אם לא הוגדר.
    """
    if not WHATSAPP_FROM:
        return None
    f = WHATSAPP_FROM.strip()
    return f if f.startswith("whatsapp:") else f"whatsapp:{f}" if f.startswith("+") else f


def send_text(to_number: str, body: str) -> str:
    """
    שולח טקסט פשוט. מעדיף Messaging Service. חוזר SID של ההודעה.
    """
    to = _normalize_to(to_number, "whatsapp")

    payload: Dict[str, str] = {"to": to, "body": body}

    if MESSAGING_SERVICE_SID:
        payload["messaging_service_sid"] = MESSAGING_SERVICE_SID
    else:
        from_ = _resolve_from_for_whatsapp()
        if not from_:
            raise RuntimeError(
                "No Messaging Service SID and no TWILIO_WHATSAPP_FROM were provided."
            )
        payload["from_"] = from_

    print(f"Twilio text payload: {payload}")
    msg = client.messages.create(**payload)
    return msg.sid


def send_content_message(
    to_number: str,
    content_sid: str,
    variables: Optional[Dict[str, str]] = None,
) -> str:
    """
    שולח תבנית Content API (Content SID + variables).
    variables יכול להיות dict או מחרוזת JSON מוכנה.
    """
    to = _normalize_to(to_number, "whatsapp")

    # Twilio מצפה ל-string של JSON בשדה content_variables
    if variables is None:
        content_variables = "{}"
    elif isinstance(variables, str):
        content_variables = variables
    else:
        content_variables = json.dumps(variables, ensure_ascii=False)

    payload: Dict[str, str] = {
        "to": to,
        "content_sid": content_sid,
        "content_variables": content_variables,
    }

    if MESSAGING_SERVICE_SID:
        payload["messaging_service_sid"] = MESSAGING_SERVICE_SID
    else:
        from_ = _resolve_from_for_whatsapp()
        if not from_:
            raise RuntimeError(
                "No Messaging Service SID and no TWILIO_WHATSAPP_FROM were provided."
            )
        payload["from_"] = from_

    print(f"Twilio content payload: {payload}")
    msg = client.messages.create(**payload)
    return msg.sid
