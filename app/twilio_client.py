import os
import json
from twilio.rest import Client

# Load credentials from environment
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # e.g. whatsapp:+14155238886 without the 'whatsapp:' prefix here

# Init client once per process
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_content_message(to_number: str, content_sid: str, vars_map: dict | None = None):
    """
    Send a WhatsApp message using a Twilio Content Template.
    - to_number: 'whatsapp:+9725xxxxxxx'
    - content_sid: the Content Template SID
    - vars_map: dict of variables that match the template placeholders (e.g. {"item1": "06:00", "item2": "06:30"})
    """
    payload = {
        "to": to_number,
        "from_": f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
        "content_sid": content_sid,
        "content_variables": json.dumps(vars_map or {}, ensure_ascii=False),
    }
    print("Twilio content payload:", payload)
    return client.messages.create(**payload)


def send_text(to_number: str, body: str):
    """
    Send a plain text WhatsApp message via Twilio (no template).
    """
    payload = {
        "to": to_number,
        "from_": f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
        "body": body,
    }
    print("Twilio text payload:", payload)
    return client.messages.create(**payload)
