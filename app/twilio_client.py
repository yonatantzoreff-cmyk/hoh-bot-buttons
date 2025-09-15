import os
# app/twilio_client.py
import json
import os
from typing import Dict, Union

from twilio.rest import Client

# ===== Env / Credentials =====
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # e.g. +14155238886

# Messaging Service that has your WhatsApp sender attached
# e.g. MGXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    raise RuntimeError("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN env vars")

if not TWILIO_MESSAGING_SERVICE_SID:
    raise RuntimeError("Missing TWILIO_MESSAGING_SERVICE_SID env var")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _normalize_to_whatsapp(number: str) -> str:
# ===== Helpers =====
def _normalize_to(to_number: str, channel: str = "whatsapp") -> str:
"""
    Ensure the 'to' number is in 'whatsapp:+E164' format.
    Accepts inputs like: '0501234567', '972501234567', '+972501234567', 'whatsapp:+972...'
    Defaults to IL if starts with '0'.
    Ensure the recipient is formatted for the requested channel.
    For WhatsApp: must be 'whatsapp:+<E164>'
    Accepts '9725...' or '+9725...' or 'whatsapp:+9725...'
   """
    if not number:
        return number

    n = number.strip()
    to = to_number.strip()

    # already has whatsapp: prefix
    if n.lower().startswith("whatsapp:"):
        return n
    if channel.lower() == "whatsapp":
        # ensure E.164
        if to.startswith("whatsapp:"):
            return to  # assume it's already correct
        if not to.startswith("+"):
            # best-effort: add '+' if missing (user often sends 9725...)
            to = f"+{to}"
        return f"whatsapp:{to}"

    # strip any accidental 'whatsapp:' that came later in the string
    if "whatsapp:" in n.lower():
        n = n.lower().replace("whatsapp:", "")
    # SMS or other channels – return E.164 as-is
    if not to.startswith("+"):
        to = f"+{to}"
    return to

    # ensure it starts with +E164
    if n.startswith("+"):
        e164 = n
    elif n.startswith("0"):
        # assume Israel if local leading zero (e.g. 050...)
        e164 = "+972" + n[1:]
    elif n.startswith("972"):
        e164 = "+" + n
    else:
        # last resort: if all digits and no plus, add '+'
        # (adjust this if you expect other country codes)
        e164 = "+" + n

    return f"whatsapp:{e164}"
def _ensure_json_string(variables: Union[str, Dict]) -> str:
    if isinstance(variables, str):
        return variables
    return json.dumps(variables, ensure_ascii=False)


def _from_whatsapp() -> str:
# ===== Public API =====
def send_text(to_number: str, body: str, channel: str = "whatsapp"):
"""
    Build the 'from_' value properly.
    Accepts either '+E164' or 'whatsapp:+E164' in the env; always returns 'whatsapp:+E164'.
    Send a plain text message via the Twilio Messaging Service.
   """
    sender = (TWILIO_WHATSAPP_NUMBER or "").strip()
    if not sender:
        return "whatsapp:None"
    if sender.lower().startswith("whatsapp:"):
        return sender
    return f"whatsapp:{sender}"
    to = _normalize_to(to_number, channel)


def send_content_message(to_number: str, content_sid: str, vars_map: dict | None = None):
payload = {
        "to": _normalize_to_whatsapp(to_number),
        "from_": _from_whatsapp(),
        "content_sid": content_sid,
        "content_variables": json.dumps(vars_map or {}, ensure_ascii=False),
        "messaging_service_sid": TWILIO_MESSAGING_SERVICE_SID,
        "to": to,
        "body": body,
}
    print("Twilio content payload:", payload)

    print(f"Twilio text payload: {payload}")
return client.messages.create(**payload)


def send_text(to_number: str, body: str):
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
        "to": _normalize_to_whatsapp(to_number),
        "from_": _from_whatsapp(),
        "body": body,
        "messaging_service_sid": TWILIO_MESSAGING_SERVICE_SID,
        "to": to,
        "content_sid": content_sid,
        "content_variables": variables_json,
}
    print("Twilio text payload:", payload)

    print(f"Twilio content payload: {payload}")
return client.messages.create(**payload)
