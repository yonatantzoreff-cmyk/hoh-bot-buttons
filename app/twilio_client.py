import os, json
from twilio.rest import Client

_account = os.getenv("TWILIO_ACCOUNT_SID")
_token = os.getenv("TWILIO_AUTH_TOKEN")
_service = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
_from = os.getenv("TWILIO_WHATSAPP_FROM")

client = Client(_account, _token)

def get_twilio():
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise RuntimeError("Missing Twilio credentials")
    return Client(sid, token)

def _dest(to: str) -> str:
    return to if to.startswith("whatsapp:") else f"whatsapp:{to}"

def send_content_message(to: str, content_sid: str, variables: dict):
    # הוצאת None והמרה למחרוזות
    clean = {str(k): ("" if v is None else str(v)) for k, v in variables.items()}
    payload = {
        "to": to,
        "content_sid": content_sid,
        "content_variables": json.dumps(clean, ensure_ascii=False),  # <-- MUST be string
    }
    if _service:
        payload["messaging_service_sid"] = _service
    elif _from:
        payload["from_"] = _from
    else:
        raise RuntimeError("Set TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_FROM")

    # אופציונלי: לוג דיבוג קצר שיעזור אם ייפול שוב
    # print(f"[twilio] content_sid={content_sid} vars={payload['content_variables']}")

    return client.messages.create(**payload)
def send_text(to: str, body: str):
    client = get_twilio()
    from_whatsapp = os.getenv("TWILIO_WHATSAPP_FROM")
    messaging_service = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    kwargs = {
        "to": _dest(to),
        "body": body,
    }
    if messaging_service:
        kwargs["messaging_service_sid"] = messaging_service
    elif from_whatsapp:
        kwargs["from_"] = from_whatsapp
    else:
        raise RuntimeError("Set either TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_FROM")
    return client.messages.create(**kwargs)
