# app/routers/webhook_new.py

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import logging
import re
import os

from app.flows.ranges import send_ranges, send_halves
from app.utils import sheets

router = APIRouter()

def _is_coordination_text(txt: str) -> bool:
    """
    בדיקה אם הטקסט שהגיע מהספק מעיד על רצון לתיאום.
    ניתן להרחיב את רשימת המילים/ביטויים לפי הצורך.
    """
    if not txt:
        return False
    txt = txt.strip()
    triggers = ["תיאום", "תיאום שעה", "תאם", "קבע שעה", "תאם שעה"]
    return any(t in txt for t in triggers)

def _normalize_phone(whatsapp_addr: str) -> str:
    """
    Twilio שולחת מספרים בפורמט whatsapp:+9725...
    פונקציה זו מחזירה את תשע הספרות האחרונות כדי להשוות למספרים בגיליון.
    """
    if not whatsapp_addr:
        return ""
    # מסירים קידומות תווים לא ספרתיים
    digits = re.sub(r"\D", "", whatsapp_addr)
    # מחזירים 9 ספרות אחרונות (מספיק לזיהוי ספק בישראל)
    return digits[-9:]

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    # Twilio שולחת application/x-www-form-urlencoded ולכן form() חשוב
    form = await request.form()
    data = {k: form.get(k) for k in form.keys()}

    # לוג שימושי לראות את כל השדות שמגיעים (כולל לחיצות וכפתורים)
    logging.info("Incoming WhatsApp form: %s",
                 {k: data[k] for k in sorted(data)})

    from_number = data.get("From")              # למשל: 'whatsapp:+9725...'
    to_number   = data.get("To")                # מספר העסק (whatsapp:+972...)
    body        = (data.get("Body") or "").strip()

    # שדות ללחיצות כפתורים / רשימות ב-Twilio (Quick Reply / List Picker)
    button_text    = (data.get("ButtonText") or "").strip()
    button_payload = (data.get("ButtonPayload") or "").strip()
    # בטוויליו ל-List Picker יש שדות ListItemTitle / ListItemValue
    list_title = (data.get("ListItemTitle") or data.get("ListTitle") or "").strip()
    list_value = (data.get("ListItemValue") or data.get("ListValue") or "").strip()

    # שלב 1: אם המשתמש כותב "תיאום" (או לחיצה שפתחה טווחים) – שולחים טווחי שעתיים
    if _is_coordination_text(body) or button_payload == "open_ranges":
        # שולחים את רשימת הטווחים למספר שפנה אלינו
        send_ranges(to_number=from_number)
        return PlainTextResponse("OK")

    # שלב 2: אם המשתמש בחר טווח שעתיים מהרשימה
    # נזהה באמצעות ID כמו range_6_8 שמגיע ב-value או ב-payload
    selection = button_payload or list_value or body or button_text
    m = re.match(r"^range_(\d{1,2})_(\d{1,2})$", selection)
    if m:
        start_h, end_h = int(m.group(1)), int(m.group(2))
        # שולחים רשימת חצאי שעות לטווח שנבחר
        send_halves(to_number=from_number, start_hour=start_h, end_hour=end_h)
        return PlainTextResponse("OK")

    # שלב 3: אם המשתמש בחר חצי שעה (לדוגמה 'slot_06_30' או '06:30')
    # ננסה לאתר פורמט slot_HH_MM או HH:MM
    slot_match = re.match(r"^(?:slot_|SLOT_)?(?P<h>\d{1,2})(?:_|:)(?P<m>\d{2})$", selection)
    if slot_match:
        hh = int(slot_match.group("h"))
        mm = int(slot_match.group("m"))
        time_str = f"{hh:02d}:{mm:02d}"

        # נעדכן את הגיליון: נמצא את השורה המתאימה לפי מספר הטלפון של הספק
        ss = sheets.open_sheet()
        events_sheet_name = os.getenv("SHEET_EVENTS_NAME")
        ws = sheets.get_worksheet(ss, events_sheet_name)
        headers = sheets.get_headers(ws)

        phone_idx = sheets.find_col_index(headers, ["supplier_phone", "phone", "טלפון"])
        load_idx  = sheets.find_col_index(
            headers,
            ["load_in_time", "load_in", "load-in time", "כניסה", "שעת כניסה"]
        )
        status_idx = sheets.find_col_index(headers, ["status", "Status"])

        if phone_idx is not None:
            rows = ws.get_all_values()
            from_norm = _normalize_phone(from_number)
            # מתחילים מאינדקס 1 (השורה השנייה) כי שורה 0 היא כותרות
            for r_i in range(1, len(rows)):
                row = rows[r_i]
                phone_cell = _normalize_phone(row[phone_idx])
                if phone_cell == from_norm:
                    # מעדכנים שעת כניסה (load_in_time)
                    if load_idx is not None:
                        ws.update_cell(r_i + 1, load_idx + 1, time_str)
                    # מעדכנים סטטוס לשלב הבא (לדוגמה 'load_in_received')
                    if status_idx is not None:
                        ws.update_cell(r_i + 1, status_idx + 1, "load_in_received")
                    break

        # אפשר להמשיך מכאן ולשלוח הודעת אישור/סיכום אם נדרש
        return PlainTextResponse("OK")

    # ברירת מחדל: מחזירים 200 OK כדי שטוויליו לא תנסה לשלוח מחדש
    return PlainTextResponse("OK")
