from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from app.flows.ranges import send_ranges, send_halves
import logging
import re

router = APIRouter()

def _is_coordination_text(txt: str) -> bool:
    if not txt:
        return False
    txt = txt.strip()
    triggers = ["תיאום", "תיאום שעה", "תאם", "קבע שעה", "תאם שעה"]
    return any(t in txt for t in triggers)

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    data = {k: form.get(k) for k in form.keys()}

    # לוג שימושי כדי לראות אילו שדות Twilio שולחת חזרה (בפרט ב-List Picker / Buttons)
    logging.info("Incoming WhatsApp form: %s", {k: data[k] for k in sorted(data)})

    from_number = data.get("From")              # למשל: 'whatsapp:+9725...'
    to_number   = data.get("To")                # מספר ה-Business (גם בפורמט whatsapp:)
    body        = (data.get("Body") or "").strip()

    # תשובות אינטראקטיביות של WhatsApp דרך Twilio (יכולות להגיע במספר שדות):
    # כפתורים:
    button_text    = (data.get("ButtonText") or "").strip()
    button_payload = (data.get("ButtonPayload") or "").strip()
    # List Picker:
    list_title = (data.get("ListItemTitle") or "").strip()
    list_value = (data.get("ListItemValue") or "").strip()
    # לעיתים Content API מחזיר גם Parameters.* — נשאיר לוגים לראות אם יש.

    # 1) אם המשתמש כתב "תיאום"/"תיאום שעה" -> שלח טווחים (שעתיים)
    if _is_coordination_text(body) or button_payload == "open_ranges":
        send_ranges(to_number=from_number)  # שולחים למי שפנה אלינו
        return PlainTextResponse("OK")

    # 2) אם המשתמש בחר טווח שעתיים מהרשימה (נזהה לפי value כמו 'range_6_8')
    selection = list_value or button_payload or body
    # דוגמאות צפויות: 'range_6_8', 'range_8_10', ...
    m = re.match(r"^range_(\d{1,2})_(\d{1,2})$", selection)
    if m:
        start_h, end_h = int(m.group(1)), int(m.group(2))
        send_halves(to_number=from_number, start_hour=start_h, end_hour=end_h)
        return PlainTextResponse("OK")

    # 3) אם המשתמש בחר חצי שעה (למשל 'slot_06_30' או טקסט כמו '06:30')
    # נגדיר פורמט מזהה שנשלח בפריטי חצי השעה: slot_HH_MM
    m2 = re.match(r"^slot_(\d{2})_(\d{2})$", selection)
    if m2:
        # כאן תוכל לבצע המשך תהליך (שמירה ב-DB/שליחת אישור וכו')
        # כרגע רק נחזיר אישור קצר, או תוכל לקרוא ל-send_confirmation(...)
        return PlainTextResponse("OK")

    # אם אנחנו לא מזהים — לא עושים כלום (Twilio דורשת 200 OK).
    return PlainTextResponse("OK")
