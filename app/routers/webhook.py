
import os, json, datetime, pytz, re
from fastapi import APIRouter, Request, Response
from app.utils import sheets
from app.twilio_client import send_content_message, send_text
from app.flows.slots import slots_for_range

router = APIRouter()
TZ = os.getenv("TZ", "Asia/Jerusalem")

def now_iso():
    return datetime.datetime.now(pytz.timezone(TZ)).isoformat()

def get_last_event_id_for(to_number: str):
    try:
        ss = sheets.open_sheet()
        ws = sheets.get_worksheet(ss, os.getenv("SHEET_MESSAGES_NAME"))
        rows = ws.get_all_values()
        for r in reversed(rows[1:]):
            if len(r) >= 4 and r[1] == "out" and (r[3] == to_number or r[3].endswith(to_number.replace("whatsapp:",""))):
                return r[2]
    except Exception:
        pass
    return ""

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    data = {k: (v if isinstance(v, str) else v.filename) for k, v in form.items()}
    from_number = data.get("From", "")
    to_number = data.get("To", "")
    body = data.get("Body", "") or ""
    button_text = data.get("ButtonText", "")
    button_payload = data.get("ButtonPayload", "")

    context = {}
    if button_payload:
        try:
            context = json.loads(button_payload)
        except Exception:
            context = {}

    try:
        ss = sheets.open_sheet()
        sheets.append_message_log(ss, {
            "timestamp": now_iso(),
            "direction": "in",
            "event_id": "",
            "to": to_number,
            "from": from_number,
            "body": body,
            "button_text": button_text,
            "button_payload": button_payload,
            "raw": json.dumps(data, ensure_ascii=False),
        })
    except Exception:
        pass

    if not context and button_payload:
        payload = (button_payload or "").strip().upper()
        event_id = get_last_event_id_for(from_number)
        if payload == "CHOOSE_TIME":
            context = {"action": "choose_time_range", "event_id": event_id, "range": "noon"}
        elif payload == "NOT_SURE":
            context = {"action": "not_sure", "event_id": event_id}
        elif payload == "NOT_CONTACT":
            context = {"action": "not_contact", "event_id": event_id}
        elif payload == "CONFIRM_SLOT":
            m = re.search(r'(\d{1,2}):(\d{2})', body or "")
            slot = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}" if m else ""
            context = {"action": "confirm_slot", "event_id": event_id, "slot": slot}
        elif payload == "CHANGE_TIME":
            context = {"action": "choose_time_range", "event_id": event_id, "range": "noon"}
        elif payload.startswith("SLOT_"):
            m = re.search(r'(\d{1,2}):(\d{2})', body or "")
            slot = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}" if m else ""
            context = {"action": "pick_slot", "event_id": event_id, "slot": slot}

    action = context.get("action")

    if action == "choose_time_range":
        range_key = context.get("range", "noon")
        slots = slots_for_range(range_key, tz=TZ)
        content_sid = os.getenv("CONTENT_SID_SLOT_LIST")
        if content_sid:
            vars_map = {f"item{i}": s for i, s in enumerate(slots[:10], start=1)}
            send_content_message(from_number, content_sid, vars_map)
        else:
            options = "\n".join([f"- {s}" for s in slots[:10]])
            send_text(from_number, f"בחר/י משבצת:\n{options}\nענה/י עם השעה (למשל 14:30)")
        return Response(content="", media_type="text/plain")

    elif action == "pick_slot":
        slot = context.get("slot", body.strip())
        content_sid = os.getenv("CONTENT_SID_CONFIRM_QR")
        if slot:
            if content_sid:
                send_content_message(from_number, content_sid, {"1": slot})
            else:
                send_text(from_number, f"לאשר את {slot}? כתוב/כתבי 'כן' או בחר/י 'שינוי שעה'")
        else:
            send_text(from_number, "לא הצלחתי להבין את השעה. אפשר לבחור שוב?")
        return Response(content="", media_type="text/plain")

    elif action == "confirm_slot":
        event_id = context.get("event_id", "")
        slot = context.get("slot", "")
        if not slot:
            m = re.search(r'(\d{1,2}):(\d{2})', body or "")
            slot = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}" if m else ""
        if event_id and slot:
            ss = sheets.open_sheet()
            sheets.update_event_time(ss, event_id, slot, status="confirmed")
            send_text(from_number, f"✅ מעולה! נועלתם על {slot}. נתראה באירוע.")
        else:
            send_text(from_number, "לא קיבלתי את כל הפרטים. ננסה שוב לבחור שעה.")
        return Response(content="", media_type="text/plain")

    elif action == "not_sure":
        event_id = context.get("event_id", "")
        ss = sheets.open_sheet()
        due = (datetime.datetime.now(pytz.timezone(TZ)) + datetime.timedelta(hours=72)).isoformat()
        sheets.set_followup_due(ss, event_id, due)
        content_sid = os.getenv("CONTENT_SID_NOT_SURE_QR")
        if content_sid:
            send_content_message(from_number, content_sid, {})
        else:
            send_text(from_number, "הבנתי, אחזור תוך 72 שעות.")
        return Response(content="", media_type="text/plain")

    elif action == "not_contact":
        content_sid = os.getenv("CONTENT_SID_CONTACT_QR")
        if content_sid:
            send_content_message(from_number, content_sid, {})
        else:
            send_text(from_number, "למי נכון לפנות בבקשה? שלחו שם + מספר טלפון.")
        return Response(content="", media_type="text/plain")

    t = (button_text or body).strip()
    m = re.search(r'(\d{1,2}):(\d{2})', t)
    if m:
        slot = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
        send_text(from_number, f"מאשר/ת {slot}? אם כן, כתבו: כן")
    else:
        send_text(from_number, "קיבלתי. אפשר לבחור מהכפתורים או לכתוב שעה בפורמט 14:30.")
    return Response(content="", media_type="text/plain")
