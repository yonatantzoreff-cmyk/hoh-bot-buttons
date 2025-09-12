import os, json
from twilio.rest import Client

def get_twilio():
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise RuntimeError("Missing Twilio credentials")
    return Client(sid, token)

def send_content_message(to: str, content_sid: str, variables: dict):
    client = get_twilio()
    from_whatsapp = os.getenv("TWILIO_WHATSAPP_FROM")
    messaging_service = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    kwargs = {
        "to": f"whatsapp:{to}" if not to.startswith("whatsapp:") else to,
        "content_sid": content_sid,
        "content_variables": json.dumps(variables or {}),
    }
    if messaging_service:
        kwargs["messaging_service_sid"] = messaging_service
    elif from_whatsapp:
        kwargs["from_"] = from_whatsapp
    else:
        raise RuntimeError("Set either TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_FROM")
    return client.messages.create(**kwargs)

def send_text(to: str, body: str):
    client = get_twilio()
    from_whatsapp = os.getenv("TWILIO_WHATSAPP_FROM")
    messaging_service = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    kwargs = {
        "to": f"whatsapp:{to}" if not to.startswith("whatsapp:") else to,
        "body": body,
    }
    if messaging_service:
        kwargs["messaging_service_sid"] = messaging_service
    elif from_whatsapp:
        kwargs["from_"] = from_whatsapp
    else:
        raise RuntimeError("Set either TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_FROM")
    return client.messages.create(**kwargs)
