# app/twilio_client.py
import json
from twilio.rest import Client
from credentials import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER, TWILIO_MESSAGING_SERVICE_SID

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def get_twilio():
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise RuntimeError("Missing Twilio credentials")
    return Client(sid, token)

def _dest(to: str) -> str:
    return to if to.startswith("whatsapp:") else f"whatsapp:{to}"

def send_content_message(to_number: str, content_sid: str, vars_map: dict):
    """
    to_number: 'whatsapp:+9725XXXXXXXX'
    content_sid: 'HXxxxxxxxxxxxxxxxxxxxxxxxxxxxx'  (Content Template SID)
    vars_map: dict של משתנים לטמפלייט
             אם הטמפלייט הוא {{1}} {{2}} => {'1': 'foo', '2': 'bar'}
             אם הטמפלייט הוא {{name}} => {'name': 'Yonatan'}
    """

    # 1) ודא שמפתחות הם מחרוזות (Twilio רגיש)
    vars_map = {str(k): v for k, v in vars_map.items()}

    # 2) הפוך למחרוזת JSON בדיוק
    content_variables_str = json.dumps(vars_map, ensure_ascii=False)

    payload = {
        "to": to_number,                       # 'whatsapp:+9725...'
        "content_sid": content_sid,            # שים לב: underscore בשם הפרמטר ב־Python SDK
        "content_variables": content_variables_str,
        # אחד מהשניים (מומלץ Messaging Service אם מוגדר כראוי ל־WhatsApp):
        "messaging_service_sid": TWILIO_MESSAGING_SERVICE_SID,
        # לחלופין:
        # "from_": f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
    }

    # 3) אל תכלול body/media/אחר ביחד עם contentSid
    # 4) לוג דיבאג לעזור למהר root-cause
    print("Twilio payload:", payload)

    msg = client.messages.create(**payload)
    return msg.sid
    
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
