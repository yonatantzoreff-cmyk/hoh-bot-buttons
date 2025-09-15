# app/twilio_client.py
import json
import os
from typing import Dict, Union

from twilio.rest import Client

# ===== Env / Credentials =====
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# Messaging Service that has your WhatsApp sender attached
# e.g. MGXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    raise RuntimeError("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN env vars")

if not TWILIO_MESSAGING_SERVICE_SID:
    raise RuntimeError("Missing TWILIO_MESSAGING_SERVICE_SID env var")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


# ===== Helpers =====
def _normalize_to(to_number: str, channel: str = "whatsapp") -> str:
    """
    Ensure the recipient is formatted for the requested channel.
    For WhatsApp: must be 'whatsapp:+<E164>'
    Accepts '9725...' or '+9725...' or 'whatsapp:+9725...'
    """
    to = to_number.strip()

    if channel.lower() == "whatsapp":
        # ensure E.164
        if to.startswith("whatsapp:"):
            return to  # assume it's already correct
        if not to.startswith("+"):
            # best-effort: add '+' if missing (user often sends 9725...)
            to = f"+{to}"
        return f"whatsapp:{to}"

    # SMS or other channels – return E.164 as-is
    if not to.startswith("+"):
        to = f"+{to}"
    return to


def _ensure_json_string(variables: Union[str, Dict]) -> str:
    if isinstance(variables, str):
        return variables
    return json.dumps(variables, ensure_ascii=False)


# ===== Public API =====
def send_text(to_number: str, body: str, channel: str = "whatsapp"):
    """
    Send a plain text message via the Twilio Messaging Service.
    """
    to = _normalize_to(to_number, channel)

    payload = {
        "messaging_service_sid": TWILIO_MESSAGING_SERVICE_SID,
        "to": to,
        "body": body,
    }

    print(f"Twilio text payload: {payload}")
    return client.messages.create(**payload)


def send_content_message(
    to_number: str,
    content_sid: str,
    content_variables: Union[str, Dict],
    channel: str = "whatsapp",
):
    """
    Send a Content Template message (e.g., List Picker) via the Messaging Service.
    - content_sid: HX..................................
    - content_variables: dict or JSON string
    """
    to = _normalize_to(to_number, channel)
    variables_json = _ensure_json_string(content_variables)

    payload = {
        "messaging_service_sid": TWILIO_MESSAGING_SERVICE_SID,
        "to": to,
        "content_sid": content_sid,
        "content_variables": variables_json,
    }

    print(f"Twilio content payload: {payload}")
    return client.messages.create(**payload)
