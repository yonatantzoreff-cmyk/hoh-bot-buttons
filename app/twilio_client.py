import os
import json
from twilio.rest import Client

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # e.g. +14155238886

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _normalize_to_whatsapp(number: str) -> str:
    """
    Ensure the 'to' number is in 'whatsapp:+E164' format.
    Accepts inputs like: '0501234567', '972501234567', '+972501234567', 'whatsapp:+972...'
    Defaults to IL if starts with '0'.
    """
    if not number:
        return number

    n = number.strip()

    # already has whatsapp: prefix
    if n.lower().startswith("whatsapp:"):
        return n

    # strip any accidental 'whatsapp:' that came later in the string
    if "whatsapp:" in n.lower():
        n = n.lower().replace("whatsapp:", "")

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


def _from_whatsapp() -> str:
    """
    Build the 'from_' value properly.
    Accepts either '+E164' or 'whatsapp:+E164' in the env; always returns 'whatsapp:+E164'.
    """
    sender = (TWILIO_WHATSAPP_NUMBER or "").strip()
    if not sender:
        return "whatsapp:None"
    if sender.lower().startswith("whatsapp:"):
        return sender
    return f"whatsapp:{sender}"


def send_content_message(to_number: str, content_sid: str, vars_map: dict | None = None):
    payload = {
        "to": _normalize_to_whatsapp(to_number),
        "from_": _from_whatsapp(),
        "content_sid": content_sid,
        "content_variables": json.dumps(vars_map or {}, ensure_ascii=False),
    }
    print("Twilio content payload:", payload)
    return client.messages.create(**payload)


def send_text(to_number: str, body: str):
    payload = {
        "to": _normalize_to_whatsapp(to_number),
        "from_": _from_whatsapp(),
        "body": body,
    }
    print("Twilio text payload:", payload)
    return client.messages.create(**payload)
