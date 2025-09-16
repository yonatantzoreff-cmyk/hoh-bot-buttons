# app/routers/webhook.py
# MVP: Buttons-only -> write time to Google Sheets by event_id

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import logging, os, re, datetime, pytz

from app.utils import sheets
from app.twilio_client import send_content_message  # משתמש רק ב-Messaging Service (לפי env)

router = APIRouter()
TZ = os.getenv("TZ", "Asia/Jerusalem")

# ------- Helpers -------

def now_iso() -> str:
    tz = pytz.timezone(TZ)
    return datetime.datetime.now(tz).isoformat()

def _get(data: dict, key: str) -> str:
    return (data.get(key) or "").strip()

def _pick_interactive_value(data: dict) -> str:
    """
    נחזיר את ה-value המועיל ביותר מהאינטראקטיב:
    ButtonPayload > ListItemValue > ButtonText > ListItemTitle > Body
    """
    return (
        _get(data, "ButtonPayload")
        or _get(data, "ListItemValue")
        or _get(data, "ButtonText")
        or _get(data, "ListItemTitle")
        or _get(data, "Body")
    )

def _append_log(spreadsheet, direction: str, event_id: str, to: str, from_: str, body: str, btn_text: str, btn_payload: str, raw: dict):
    try:
        sheets.append_message_log(spreadsheet, {
            "timestamp": now_iso(),
            "direction": direction,
            "event_id": event_id,
            "to": to,
            "from": from_,
            "body": body,
            "button_text": btn_text,
            "button_payload": btn_payload,
            "raw": str({k: raw[k] for k in sorted(raw.keys())}),
        })
    except Exception as e:
        logging.exception(f"[LOG] append_message_log failed: {e}")

def _send_ranges(to_number: str, event_id: str, variables: dict | None = None):
    """
    שליחת תבנית 'טווחים' (שעתיים). דורש CONTENT_SID_RANGES.
    """
    sid = os.getenv("CONTENT_SID_RANGES")
    if not sid:
        logging.warning("Missing CONTENT_SID_RANGES; skipping send_ranges.")
        return
    vars_out = variables.copy() if variables else {}
    vars_out.setdefault("5", event_id)  # דוגמה: פרמטר 5 = event_id בתבנית
    send_content_message(to_number, sid, vars_out)

def _send_halves(to_number: str, start_hour: int, end_hour: int, event_id: str, variables: dict | None = None):
    """
    שליחת תבנית 'חצאי-שעה' עבור טווח שנבחר. דורש CONTENT_SID_HALVES.
    """
    sid = os.getenv("CONTENT_SID_HALVES")
    if not sid:
        logging.warning("Missing CONTENT_SID_HALVES; skipping send_halves.")
        return
    vars_out = variables.copy() if variables else {}
    # אפשר להעביר לתבנית את תיאור הטווח, למשל "14:00–16:00"
    vars_out.setdefault("5", event_id)
    vars_out.setdefault("6", f"{start_hour:02d}:00–{end_hour:02d}:00")
    send_content_message(to_number, sid, vars_out)

def _update_time_by_event(event_id: str, hh: int, mm: int) -> bool:
    """
    כתיבת HH:MM לעמודת load_in_time של event_id, ועדכון סטטוס.
    """
    ss = sheets.open_sheet()
    time_str = f"{hh:02d}:{mm:02d}"
    ok = False
    try:
        ok = sheets.update_event_time(ss, event_id, time_str, status="load_in_received")
    except Exception as e:
        logging.exception(f"[SHEETS] update_event_time error: {e}")
    return ok

# ------- Webhook -------

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    # Twilio שולחת application/x-www-form-urlencoded
    form = await request.form()
    data = {k: form.get(k) for k in form.keys()}

    # לוג כללי — עוזר לראות אילו שדות מגיעים (Buttons/List)
    try:
        logging.info("[WA IN] keys=%s sample=%s",
                     list(sorted(data.keys())),
                     {k: data[k] for k in list(sorted(data.keys()))[:10]})
    except Exception:
        pass

    from_number = _get(data, "From")         # whatsapp:+972...
    to_number   = _get(data, "To")           # whatsapp:+972... (המספר שלנו)
    body        = _get(data, "Body")
    button_text = _get(data, "ButtonText")
    button_payload = _get(data, "ButtonPayload")
    list_title  = _get(data, "ListItemTitle")
    list_value  = _get(data, "ListItemValue")

    # ערך הבחירה "הטוב ביותר"
    selection = _pick_interactive_value(data)

    # נשמור לוג לכל הודעה נכנסת (לגיליון נפרד כפי שביקשת)
    try:
        ss = sheets.open_sheet()
        _append_log(ss, "incoming", "", to_number, from_number, body, button_text, button_payload, data)
    except Exception as e:
        logging.exception(f"[LOG] failed (initial append): {e}")

    # --- 1) פתיחת טווחים: open_ranges_EVT-10023 ---
    m_open = re.match(r"^open_ranges_(?P<event>EVT-[A-Za-z0-9\-]+)$", selection)
    if m_open:
        event_id = m_open.group("event")
        _send_ranges(to_number=from_number, event_id=event_id)
        # לוג עם event_id ידוע
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: ranges", data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # --- 2) בחירת טווח שעתיים: range_14_16_EVT-10023 ---
    m_range = re.match(r"^range_(?P<s>\d{1,2})_(?P<e>\d{1,2})_(?P<event>EVT-[A-Za-z0-9\-]+)$", selection)
    if m_range:
        start_h = int(m_range.group("s"))
        end_h   = int(m_range.group("e"))
        event_id = m_range.group("event")
        _send_halves(to_number=from_number, start_hour=start_h, end_hour=end_h, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", f"sent: halves {start_h}-{end_h}", data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # --- 3) בחירת חצי שעה סופית: slot_EVT-10023_14_00 או 14:00 ---
    # פורמט מועדף: slot_EVT-XXXX_14_00 (מגיע ב-ButtonPayload/ListItemValue)
    m_slot = re.match(r"^slot_(?P<event>EVT-[A-Za-z0-9\-]+)_(?P<h>\d{1,2})_(?P<m>\d{2})$", selection)
    if m_slot:
        event_id = m_slot.group("event")
        hh = int(m_slot.group("h"))
        mm = int(m_slot.group("m"))
        ok = _update_time_by_event(event_id, hh, mm)

        try:
            ss = sheets.open_sheet()
            _append_log(ss, "incoming", event_id, to_number, from_number,
                        f"slot chosen {hh:02d}:{mm:02d}", button_text, button_payload, data)
        except Exception:
            pass

        if not ok:
            logging.warning(f"[SHEETS] update_event_time returned False for {event_id}")
        return PlainTextResponse("OK", status_code=200)

    # אופציה שנייה — אם התבנית מחזירה רק שעה בטקסט, ונושא ה-event_id הועבר בשדה אחר,
    # אפשר לתמוך גם בזה: ListItemTitle='14:00', ButtonPayload='slot_EVT-10023'
    m_slot_split = re.match(r"^slot_(?P<event>EVT-[A-Za-z0-9\-]+)$", button_payload)
    m_time_txt   = re.match(r"^(?P<h>\d{1,2}):(?P<m>\d{2})$", list_title or button_text or body)
    if m_slot_split and m_time_txt:
        event_id = m_slot_split.group("event")
        hh = int(m_time_txt.group("h"))
        mm = int(m_time_txt.group("m"))
        ok = _update_time_by_event(event_id, hh, mm)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "incoming", event_id, to_number, from_number,
                        f"slot chosen {hh:02d}:{mm:02d}", button_text, button_payload, data)
        except Exception:
            pass
        if not ok:
            logging.warning(f"[SHEETS] update_event_time returned False for {event_id}")
        return PlainTextResponse("OK", status_code=200)

    # אם זה לא אחד מהמקרים — אנחנו במוד "כפתורים בלבד" ואין פעולה לבצע
    return PlainTextResponse("OK", status_code=200)
