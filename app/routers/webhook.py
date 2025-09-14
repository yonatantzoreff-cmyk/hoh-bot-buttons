import os, json, datetime, pytz, re
from fastapi import APIRouter, Request, Response
from app.utils import sheets
from app.twilio_client import send_content_message, send_text
from app.flows.ranges import send_ranges, send_halves

router = APIRouter()
TZ = os.getenv("TZ", "Asia/Jerusalem")

def now_iso():
    return datetime.datetime.now(pytz.timezone(TZ)).isoformat()

def parse_twilio_list_response(form: dict):
    """
    Extract the ID and title of a selected list item from Twilio's interactive list response.
    Tries multiple possible keys because Twilio's payloads vary.
    Returns a tuple (item_id, item_title) or (None, None) if no response found.
    """
    raw = form.get("ListResponse") or form.get("InteractiveResponse")
    if raw:
        try:
            data = json.loads(raw)
            id_ = (
                data.get("Id")
                or data.get("id")
                or (data.get("Reply") or {}).get("Id")
                or (data.get("reply") or {}).get("id")
                or (data.get("list") or {}).get("reply", {}).get("id")
            )
            title = (
                data.get("Title")
                or data.get("title")
                or (data.get("Reply") or {}).get("Title")
                or (data.get("reply") or {}).get("title")
                or (data.get("list") or {}).get("reply", {}).get("title")
                or ""
            )
            if id_:
                return id_, title
        except Exception:
            pass
    for key in ("ListResponse.Id", "InteractiveResponse.Id"):
        if key in form:
            return form[key], form.get("ListResponse.Title") or form.get("InteractiveResponse.Title") or ""
    return None, None

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    data = {k: (v if isinstance(v, str) else v.filename) for k, v in form.items()}
    from_number = data.get("From", "")
    to_number = data.get("To", "")
    body = data.get("Body", "") or ""
    button_text = data.get("ButtonText", "")
    button_payload = data.get("ButtonPayload", "")

    # Log incoming message
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

    text = (button_text or body).strip()

    # Trigger to start range selection
    if text in ("תיאום", "תיאום שעה", "לתאם", "slot"):
        send_ranges(from_number)
        return Response(content="", media_type="text/plain")

    # Parse interactive list response
    item_id, item_title = parse_twilio_list_response(data)

    if item_id:
        # User selected a 2-hour range; send half-hour slots
        if item_id.startswith("SLOT_"):
            send_halves(from_number, item_id)
            return Response(content="", media_type="text/plain")

        # User selected a half-hour slot (IDs TIME_A..TIME_E in template)
        if item_id in ("TIME_A", "TIME_B", "TIME_C", "TIME_D", "TIME_E"):
            chosen_time = item_title or text
            # Optionally update event or sheet here
            # Log the chosen time
            try:
                ss = sheets.open_sheet()
                sheets.append_message_log(ss, {
                    "timestamp": now_iso(),
                    "direction": "in",
                    "event_id": "",
                    "to": to_number,
                    "from": from_number,
                    "body": chosen_time,
                    "button_text": "",
                    "button_payload": "",
                    "raw": json.dumps(data, ensure_ascii=False),
                })
            except Exception:
                pass
            # Send confirmation text
            send_text(from_number, f"✅ מעולה! נועלתם על {chosen_time}. נתראה באירוע.")
            return Response(content="", media_type="text/plain")

    # Fallback: no action taken
    return Response(content="", media_type="text/plain")
