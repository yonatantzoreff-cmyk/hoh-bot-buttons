# app/twilio_client.py
from __future__ import annotations
import os
import json
from typing import Optional, Dict, Any
from twilio.rest import Client

# ENV (Render/Dotenv)
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
DEFAULT_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")  # MGxxxxxxxx

if not ACCOUNT_SID or not AUTH_TOKEN:
    raise RuntimeError("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN env vars")

client = Client(ACCOUNT_SID, AUTH_TOKEN)


def _normalize_to(to_number: str, channel: str = "whatsapp") -> str:
    """החזר כתובת מהפורמט הנכון, למשל whatsapp:+9725..."""
    to_number = to_number.strip()
    prefix = f"{channel}:"
    if not to_number.startswith(prefix):
        return f"{prefix}{to_number}"
    return to_number


def send_text(
    to: str,
    body: str,
    messaging_service_sid: Optional[str] = None,
    channel: str = "whatsapp",
) -> Any:
    """שליחת טקסט רגיל (לא Content Template)."""
    to_addr = _normalize_to(to, channel=channel)
    msid = messaging_service_sid or DEFAULT_MESSAGING_SERVICE_SID

    if not msid:
        raise RuntimeError("Missing Messaging Service SID (TWILIO_MESSAGING_SERVICE_SID).")

    payload: Dict[str, Any] = {
        "to": to_addr,
        "messaging_service_sid": msid,
        "body": body,
    }
    return client.messages.create(**payload)


def send_content_message(
    to: str,
    content_sid: str,
    variables: Dict[str, Any] | str | None = None,
    messaging_service_sid: Optional[str] = None,
    channel: str = "whatsapp",
) -> Any:
    """
    שליחת הודעת WhatsApp דרך Content Template.
    תואם גם קריאות פוזיציונליות (to, content_sid, variables) וגם מילות מפתח.
    """
    to_addr = _normalize_to(to, channel=channel)
    msid = messaging_service_sid or DEFAULT_MESSAGING_SERVICE_SID

    if not msid:
        raise RuntimeError("Missing Messaging Service SID (TWILIO_MESSAGING_SERVICE_SID).")

    # Twilio מצפה למחרוזת JSON בשדה content_variables
    if variables is None:
        content_variables = "{}"
    elif isinstance(variables, str):
        content_variables = variables
    else:
        content_variables = json.dumps(variables, ensure_ascii=False)

    payload: Dict[str, Any] = {
        "to": to_addr,
        "messaging_service_sid": msid,
        "content_sid": content_sid,
        "content_variables": content_variables,
    }
    return client.messages.create(**payload)
