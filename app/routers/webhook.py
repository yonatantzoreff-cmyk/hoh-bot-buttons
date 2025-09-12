import os, json, datetime, pytz
from fastapi import APIRouter, Request, Response
from app.utils import sheets
from app.twilio_client import send_content_message, send_text
from app.flows.slots import slots_for_range

router = APIRouter()

TZ = os.getenv("TZ", "Asia/Jerusalem")

def now_iso():
    return datetime.datetime.now(pytz.timezone(TZ)).isoformat()

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    """Handle inbound WhatsApp messages & button presses from Twilio."""
    form = await request.form()
    data = {k: (v if isinstance(v, str) else v.filename) for k, v in form.items()}
    # Common fields
    from_number = data.get("From", "")
    wa_id = data.get("WaId", "")
    to_number = data.get("To", "")
    body = data.get("Body", "") or ""
    button_text = data.get("ButtonText", "")
    button_payload = data.get("ButtonPayload", "")
    profile_name = data.get("ProfileName", "")
    # Optional custom context we pass in payloads
    context = {}
    if button_payload:
        try:
            # We pass small JSON payloads in id (<=200 chars). Try to decode if looks like json.
            context = json.loads(button_payload)
        except Exception:
            context = {}
    # Log the inbound
    try:
        ss = sheets.open_sheet()
        sheets.append_message_log(ss, {
            "timestamp": now_iso(),
            "direction": "in",
            "event_id": context.get("event_id",""),
            "to": to_number,
            "from": from_number,
            "body": body,
            "button_text": button_text,
            "button_payload": button_payload,
            "raw": json.dumps(data, ensure_ascii=False),
        })
    except Exception as e:
        # best effort logging; continue
        pass

    # Route based on payload / body
    action = context.get("action")
    if action == "choose_time_range":
        # Send list of slots for selected range
        range_key = context.get("range", "noon")
        event_id = context.get("event_id", "")
        slots = slots_for_range(range_key, tz=TZ)
        # Build list-picker variables dynamically (up to 10 items)
        items = []
        for s in slots:
            items.append({"item": s, "id": json.dumps({"action":"pick_slot","event_id":event_id,"slot":s}), "description": f"בחירת {s}"})
        content_sid = os.getenv("CONTENT_SID_SLOT_LIST")
        if content_sid:
            send_content_message(from_number, content_sid, {
                "1": f"בחר/י משבצת של חצי שעה",
                "button": "בחר/י",
                "items": items
            })
        else:
            # Fallback to text menu
            options = "\n".join([f"- {s}" for s in slots])
            send_text(from_number, f"בחר/י משבצת:\n{options}\nענה/י עם השעה המדויקת (לדוגמה 14:30)")
        return Response(content="", media_type="text/plain")
    elif action == "pick_slot":
        # User picked a specific half-hour slot
        event_id = context.get("event_id", "")
        slot = context.get("slot", body.strip())
        # Confirm with QR buttons
        content_sid = os.getenv("CONTENT_SID_CONFIRM_QR")
        if content_sid:
            send_content_message(from_number, content_sid, {"1": slot, "2": event_id, "3": "לא, חזור"})
        else:
            send_text(from_number, f"לאשר {slot}? כתוב/כתבי 'כן' או 'לא'")
        return Response(content="", media_type="text/plain")
    elif action == "confirm_slot":
        # Write to sheet
        event_id = context.get("event_id", "")
        slot = context.get("slot", "")
        ss = sheets.open_sheet()
        sheets.update_event_time(ss, event_id, slot, status="confirmed")
        send_text(from_number, f"✅ מעולה! נועלתם על {slot}. נתראה באירוע.")
        return Response(content="", media_type="text/plain")
    elif action == "not_sure":
        event_id = context.get("event_id", "")
        ss = sheets.open_sheet()
        due = (datetime.datetime.now(pytz.timezone(TZ)) + datetime.timedelta(hours=72)).isoformat()
        sheets.set_followup_due(ss, event_id, due)
        # Acknowledge
        content_sid = os.getenv("CONTENT_SID_NOT_SURE_QR")
        if content_sid:
            send_content_message(from_number, content_sid, {"1": "הבנתי, אחזור תוך 72 שעות"})
        else:
            send_text(from_number, "הבנתי, אחזור תוך 72 שעות.")
        return Response(content="", media_type="text/plain")
    elif action == "not_contact":
        # Ask for a new contact
        content_sid = os.getenv("CONTENT_SID_CONTACT_QR")
        if content_sid:
            send_content_message(from_number, content_sid, {})
        else:
            send_text(from_number, "למי נכון לפנות בבקשה? שלחו שם + מספר טלפון (בפורמט בינלאומי).")
        return Response(content="", media_type="text/plain")
    else:
        # If user typed "בחירת שעה" or used initial buttons, deduce from text
        t = (button_text or body).strip()
        if t in ["בחירת שעה", "1"]:
            # Offer ranges via QR with payloads
            content_sid = os.getenv("CONTENT_SID_INIT_QR")  # reuse init if includes ranges? else send a separate
            # We'll craft ranges QR ad-hoc with SLOT_LIST later, for now ask which חלון זמן
            # Fallback: text ranges
            send_text(from_number, "בחר/י חלון זמן: בוקר / צהריים / אחה\"צ / לילה")
        elif t in ["אני עוד לא יודע", "2"]:
            # not sure
            event_id = ""
            content_sid = os.getenv("CONTENT_SID_NOT_SURE_QR")
            if content_sid:
                send_content_message(from_number, content_sid, {"1":"הבנתי, אחזור תוך 72 שעות"})
            else:
                send_text(from_number, "הבנתי, אחזור תוך 72 שעות.")
        elif t in ["אני לא איש הקשר", "3"]:
            content_sid = os.getenv("CONTENT_SID_CONTACT_QR")
            if content_sid:
                send_content_message(from_number, content_sid, {})
            else:
                send_text(from_number, "למי נכון לפנות בבקשה? שלחו שם + מספר טלפון (בפורמט בינלאומי).")
        else:
            # Attempt to parse HH:MM and write
            import re
            m = re.search(r'(\d{1,2}):(\d{2})', t)
            if m:
                hh, mm = m.groups()
                slot = f"{int(hh):02d}:{int(mm):02d}"
                # event id unknown from context - in real flow, include event_id in payloads
                send_text(from_number, f"מאשר/ת {slot}? אם כן, כתבו: כן")
            else:
                send_text(from_number, "קיבלתי. אפשר לבחור מהכפתורים או לכתוב שעה בפורמט 14:30.")
        return Response(content="", media_type="text/plain")
