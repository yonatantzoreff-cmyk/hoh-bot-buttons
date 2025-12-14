# app/twilio_client.py
from __future__ import annotations
import os
import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from twilio.rest import Client

# ENV (Render/Dotenv)
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
DEFAULT_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")  # MGxxxxxxxx
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")
STATUS_CALLBACK_PATH = os.getenv("TWILIO_STATUS_CALLBACK_PATH", "/twilio-status")
EXPLICIT_STATUS_CALLBACK_URL = os.getenv("TWILIO_STATUS_CALLBACK_URL")

if not ACCOUNT_SID or not AUTH_TOKEN:
    raise RuntimeError("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN env vars")

logger = logging.getLogger(__name__)
client = Client(ACCOUNT_SID, AUTH_TOKEN)


def _build_status_callback_url() -> Optional[str]:
    """Derive the status callback URL for Twilio message tracking.

    Twilio requires an absolute URL. If neither ``TWILIO_STATUS_CALLBACK_URL`` nor
    ``PUBLIC_BASE_URL`` (to build ``<base>/<path>``) is configured with a scheme and
    host, we return ``None`` so calls proceed without a callback instead of failing
    with ``HTTP 400``.
    """

    if EXPLICIT_STATUS_CALLBACK_URL:
        parsed = urlparse(EXPLICIT_STATUS_CALLBACK_URL)
        if parsed.scheme and parsed.netloc:
            return EXPLICIT_STATUS_CALLBACK_URL
        logger.warning(
            "TWILIO_STATUS_CALLBACK_URL must be an absolute URL; ignoring value: %s",
            EXPLICIT_STATUS_CALLBACK_URL,
        )

    if PUBLIC_BASE_URL:
        parsed_base = urlparse(PUBLIC_BASE_URL)
        if parsed_base.scheme and parsed_base.netloc:
            base = PUBLIC_BASE_URL.rstrip("/")
            path = STATUS_CALLBACK_PATH if STATUS_CALLBACK_PATH.startswith("/") else f"/{STATUS_CALLBACK_PATH}"
            return f"{base}{path}"
        logger.warning(
            "PUBLIC_BASE_URL must be an absolute URL; ignoring value: %s", PUBLIC_BASE_URL
        )

    logger.warning(
        "No absolute status callback URL configured; Twilio delivery status tracking will be disabled."
    )
    return None


STATUS_CALLBACK_URL = _build_status_callback_url()


def _normalize_to(to_number: str, channel: str = "whatsapp") -> str:
    """Return the address in the correct format, e.g. whatsapp:+9725..."""

    if not to_number:
        raise ValueError("Recipient phone number is required")

    to_number = to_number.strip()
    if not to_number:
        raise ValueError("Recipient phone number is required")

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

    # Defensive: never send a bare "OK" message to the user
    if body is not None and body.strip().upper() == "OK":
        logging.info("twilio_client.send_text: skipping bare 'OK' message to %s", to)
        return None

    normalized_body = body.strip()
    if normalized_body.lower() in {"ok", "success"}:
        logger.info("Skipping sending acknowledgment message: %s", normalized_body)
        return None

    to_addr = _normalize_to(to, channel=channel)
    msid = messaging_service_sid or DEFAULT_MESSAGING_SERVICE_SID

    if not msid:
        raise RuntimeError("Missing Messaging Service SID (TWILIO_MESSAGING_SERVICE_SID).")

    payload: Dict[str, Any] = {
        "to": to_addr,
        "messaging_service_sid": msid,
        "body": body,
    }
    if STATUS_CALLBACK_URL:
        payload["status_callback"] = STATUS_CALLBACK_URL
    return client.messages.create(**payload)


def send_confirmation_message(to_number: str, event_date: str, setup_time: str, event_name: str):
    """
    שולח הודעת WhatsApp חופשית (session message) בעברית עם שורות חדשות.
    אם מוגדר TWILIO_MESSAGING_SERVICE_SID – שלח דרכו; אחרת שלח מ-TWILIO_WHATSAPP_FROM.
    """
    messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM")

    body = (
        "—הודעת אישור—\n"
        "תודה, השעה התקבלה!\n"
        f"ניפגש בתאריך {event_date}, בשעה {setup_time}, לאירוע {event_name}\n"
        "אשלח לך איש קשר בסמוך למועד האירוע"
    )

    params: Dict[str, Any] = {
        "to": _normalize_to(to_number, channel="whatsapp"),
        "body": body,
    }

    if messaging_service_sid:
        params["messaging_service_sid"] = messaging_service_sid
    else:
        if not from_number:
            raise RuntimeError("Missing TWILIO_WHATSAPP_FROM env var for WhatsApp session message")
        params["from_"] = from_number

    if STATUS_CALLBACK_URL:
        params["status_callback"] = STATUS_CALLBACK_URL

    client.messages.create(**params)


def send_content_message(
    to: str,
    content_sid: str,
    content_variables: Dict[str, Any] | str | None = None,
    messaging_service_sid: Optional[str] = None,
    channel: str = "whatsapp",
) -> Any:
    """
    Send a WhatsApp Content Template message.

    :param to: recipient phone (with or without the "whatsapp:" prefix)
    :param content_sid: Twilio Content SID
    :param content_variables: variables dict to be JSON-encoded for Twilio
    :param messaging_service_sid: optional override for messaging service
    :param channel: messaging channel (defaults to "whatsapp")
    """

    to_addr = _normalize_to(to, channel=channel)
    msid = messaging_service_sid or DEFAULT_MESSAGING_SERVICE_SID

    if not msid:
        raise RuntimeError("Missing Messaging Service SID (TWILIO_MESSAGING_SERVICE_SID).")

    if content_variables is None:
        content_variables_json = "{}"
    elif isinstance(content_variables, str):
        content_variables_json = content_variables
    else:
        content_variables_json = json.dumps(content_variables, ensure_ascii=False)

    payload: Dict[str, Any] = {
        "to": to_addr,
        "messaging_service_sid": msid,
        "content_sid": content_sid,
        "content_variables": content_variables_json,
    }
    if STATUS_CALLBACK_URL:
        payload["status_callback"] = STATUS_CALLBACK_URL
    return client.messages.create(**payload)
