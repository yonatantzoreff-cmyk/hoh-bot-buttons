import json
import logging
from os import getenv
from twilio.rest import Client

ACCOUNT_SID = getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN  = getenv("TWILIO_AUTH_TOKEN")
MESSAGING_SERVICE_SID = getenv("TWILIO_MESSAGING_SERVICE_SID")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

def send_content_message(to: str, content_sid: str, variables: dict | None = None):
    """
    שליחת הודעת Content API דרך Messaging Service (מומלץ ל-WhatsApp).
    """
    if not MESSAGING_SERVICE_SID:
        raise RuntimeError("ENV MESSAGING_SERVICE_SID is missing")

    payload = {
        "messaging_service_sid": MESSAGING_SERVICE_SID,
        "to": to if to.startswith("whatsapp:") else f"whatsapp:{to}",
        "content_sid": content_sid,
        "content_variables": json.dumps(variables or {}),
    }
    logging.info("Twilio content payload: %s", payload)
    return client.messages.create(**payload)
