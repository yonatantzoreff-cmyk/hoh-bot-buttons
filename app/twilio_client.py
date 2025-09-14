import json
from twilio.rest import Client
from credentials import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_MESSAGING_SERVICE_SID,
    TWILIO_WHATSAPP_NUMBER,
)

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def send_content_message(to_number: str, content_sid: str, vars_map: dict):
    # vars_map חייב להיות שמות המשתנים בדיוק כפי שהגדרת בטמפלט
    vars_map = {str(k): v for k, v in vars_map.items()}
    content_variables_str = json.dumps(vars_map, ensure_ascii=False)

    payload = {
        "to": to_number,                      # 'whatsapp:+9725...'
        "content_sid": content_sid,           # HX...
        "content_variables": content_variables_str,
        "messaging_service_sid": TWILIO_MESSAGING_SERVICE_SID,
        # לחלופין (לא שניים יחד):
        # "from_": f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
    }

    print("Twilio payload:", payload)
    return client.messages.create(**payload)
