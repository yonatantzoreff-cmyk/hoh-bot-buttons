# app/routers/webhook.py
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import logging, os, re, datetime, pytz

from app.utils import sheets
from app.twilio_client import send_content_message

router = APIRouter()
TZ = os.getenv("TZ", "Asia/Jerusalem")

# ---------- Helpers ----------
def now_iso() -> str:
    tz = pytz.timezone(TZ)
    return datetime.datetime.now(tz).isoformat()

def _get(d: dict, k: str) -> str:
    return (d.get(k) or "").strip()

def _pick_interactive_value(d: dict) -> str:
    return (_get(d, "ButtonPayload")
            or _get(d, "ListItemValue")
            or _get(d, "ButtonText")
            or _get(d, "ListItemTitle")
            or _get(d, "Body"))

def _append_log(spreadsheet, direction: str, event_id: str, to: str, from_: str,
                body: str, btn_text: str, btn_payload: str, raw: dict):
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
    sid = os.getenv("CONTENT_SID_RANGES")
    if not sid:
        logging.warning("Missing CONTENT_SID_RANGES; skipping send_ranges.")
        return
    vars_out = dict(variables or {})
    vars_out["5"] = event_id
    send_content_message(to_number, sid, vars_out)

def _send_halves(to_number: str, start_hour: int, end_hour: int, event_id: str,
                 variables: dict | None = None):
    sid = os.getenv("CONTENT_SID_HALVES")
    if not sid:
        logging.warning("Missing CONTENT_SID_HALVES; skipping send_halves.")
        return
    vars_out = dict(variables or {})
    vars_out["5"] = event_id
    vars_out["6"] = f"{start_hour:02d}:00–{end_hour:02d}:00"
    send_content_message(to_number, sid, vars_out)

def _send_not_sure(to_number: str, event_id: str, variables: dict | None = None):
    sid = os.getenv("CONTENT_SID_NOT_SURE_QR")
    if not sid:
        logging.warning("Missing CONTENT_SID_NOT_SURE_QR; skipping send_not_sure.")
        return
    vars_out = dict(variables or {})
    vars_out["5"] = event_id
    send_content_message(to_number, sid, vars_out)

def _send_contact(to_number: str, event_id: str, variables: dict | None = None):
    sid = os.getenv("CONTENT_SID_CONTACT_QR")
    if not sid:
        logging.warning("Missing CONTENT_SID_CONTACT_QR; skipping send_contact.")
        return
    vars_out = dict(variables or {})
    vars_out["5"] = event_id
    send_content_message(to_number, sid, vars_out)

def _clean_event_id(value: str) -> str:
    """
    מחלץ מזהה אירוע תקין מהטקסט.
    אם הגיעו כפילויות כמו 'EVT-EVT-10023' או טקסט ארוך שמכיל כמה מופעים,
    ניקח את ההופעה האחרונה בפורמט EVT-XXXXX.
    """
    if not value:
        return value
    matches = re.findall(r"EVT-[A-Za-z0-9\-]+", value)
    if matches:
        return matches[-1]  # ההופעה האחרונה היא המזהה הנכון (למשל 'EVT-10023')
    return value.strip()

def _update_time_by_event(event_id: str, hh: int, mm: int) -> bool:
    ss = sheets.open_sheet()
    event_id = _clean_event_id(event_id)
    time_str = f"{hh:02d}:{mm:02d}"
    try:
        ok = sheets.update_event_time(ss, event_id, time_str, status="load_in_received")
        if not ok:
            logging.warning(f"[SHEETS] update_event_time returned False for {event_id}")
        return ok
    except Exception as e:
        logging.exception(f"[SHEETS] update_event_time error: {e}")
        return False

def _update_status_by_event(event_id: str, status: str) -> bool:
    ss = sheets.open_sheet()
    event_id = _clean_event_id(event_id)
    try:
        return sheets.update_event_time(ss, event_id, None, status=status)  # type: ignore[arg-type]
    except TypeError:
        try:
            ws = sheets.get_worksheet(ss, os.getenv("SHEET_EVENTS_NAME"))
            headers = sheets.get_headers(ws)
            event_idx  = sheets.find_col_index(headers, ["event_id","Event ID","eventId"])
            status_idx = sheets.find_col_index(headers, ["status","Status","סטטוס"])
            if event_idx is None or status_idx is None:
                logging.warning("[SHEETS] missing event_id/status columns for manual update.")
                return False
            rows = ws.get_all_values()
            for r_i in range(1, len(rows)):
                row = rows[r_i]
                if event_idx < len(row) and (row[event_idx] or "").strip() == event_id:
                    ws.update_cell(r_i + 1, status_idx + 1, status)
                    return True
            return False
        except Exception as e:
            logging.exception(f"[SHEETS] manual status update failed: {e}")
            return False
    except Exception as e:
        logging.exception(f"[SHEETS] update_status_by_event error: {e}")
        return False

def _normalize_phone(num: str) -> str:
    return re.sub(r"\D", "", num or "")[-9:]

def _resolve_event_id_for_phone(wa_from: str) -> str | None:
    ss = sheets.open_sheet()
    ws = sheets.get_worksheet(ss, os.getenv("SHEET_EVENTS_NAME"))
    headers = sheets.get_headers(ws)

    phone_idx  = sheets.find_col_index(headers, ["supplier_phone","suplier_phone","phone","טלפון"])
    event_idx  = sheets.find_col_index(headers, ["event_id","Event ID","eventId"])
    status_idx = sheets.find_col_index(headers, ["status","Status","סטטוס"])

    if phone_idx is None or event_idx is None:
        logging.warning("[SHEETS] missing columns (supplier_phone/event_id).")
        return None

    rows = ws.get_all_values()
    want = _normalize_phone(wa_from)
    candidates = []
    for r_i in range(1, len(rows)):
        row = rows[r_i]
        if len(row) <= max(phone_idx, event_idx):
            continue
        phone_cell = _normalize_phone(row[phone_idx])
        if phone_cell == want:
            eid = (row[event_idx] or "").strip()
            st  = (row[status_idx] or "").strip().lower() if status_idx is not None and status_idx < len(row) else ""
            if eid:
                candidates.append((eid, st))

    if not candidates:
        logging.info(f"[SHEETS] no event found for phone {want}")
        return None

    preferred = {"waiting_load_in","pending","needs_time","ממתין","ממתין לשעת כניסה",""}
    for eid, st in candidates:
        if st in preferred:
            return _clean_event_id(eid)
    return _clean_event_id(candidates[0][0])

# ---------- Webhook ----------
@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    data = {k: form.get(k) for k in form.keys()}

    try:
        logging.info("[WA IN] keys=%s sample=%s",
                     list(sorted(data.keys())),
                     {k: data[k] for k in list(sorted(data.keys()))[:10]})
    except Exception:
        pass

    from_number = _get(data, "From")
    to_number   = _get(data, "To")
    body        = _get(data, "Body")
    button_text = _get(data, "ButtonText")
    button_payload = _get(data, "ButtonPayload")
    list_title  = _get(data, "ListItemTitle")
    list_value  = _get(data, "ListItemValue")

    selection = _pick_interactive_value(data)
    logging.info(f"[WA IN] selection={selection!r}")

    # לוג לשונית ההודעות
    try:
        ss = sheets.open_sheet()
        _append_log(ss, "incoming", "", to_number, from_number, body, button_text, button_payload, data)
    except Exception as e:
        logging.exception(f"[LOG] failed (initial append): {e}")

    # -------- תאימות ל-Quick Reply קיימים --------
    # CHOOSE_TIME -> פותח טווחים על סמך event_id משוחזר
    if (data.get("MessageType") == "button" and button_payload.upper() == "CHOOSE_TIME"):
        event_id = _resolve_event_id_for_phone(from_number)
        if not event_id:
            logging.warning("[WA IN] CHOOSE_TIME but event_id not found for phone.")
            return PlainTextResponse("OK", status_code=200)
        _send_ranges(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: ranges (from CHOOSE_TIME)", data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # NOT_SURE
    if (data.get("MessageType") == "button" and button_payload.upper() == "NOT_SURE"):
        event_id = _resolve_event_id_for_phone(from_number)
        if event_id:
            _send_not_sure(to_number=from_number, event_id=event_id)
            _update_status_by_event(event_id, "supplier_not_sure")
            try:
                ss = sheets.open_sheet()
                _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: not_sure", data)
            except Exception:
                pass
        return PlainTextResponse("OK", status_code=200)

    # NOT_CONTACT
    if (data.get("MessageType") == "button" and button_payload.upper() == "NOT_CONTACT"):
        event_id = _resolve_event_id_for_phone(from_number)
        if event_id:
            _send_contact(to_number=from_number, event_id=event_id)
            _update_status_by_event(event_id, "contact_required")
            try:
                ss = sheets.open_sheet()
                _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: contact", data)
            except Exception:
                pass
        return PlainTextResponse("OK", status_code=200)

    # -------- הזרימה הסטנדרטית עם event_id בפיילוד --------
    # open_ranges_EVT-XXXX
    m_open = re.match(r"^open_ranges_(?P<event>EVT-[A-Za-z0-9\-]+)$", selection)
    if m_open:
        event_id = _clean_event_id(m_open.group("event"))
        _send_ranges(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: ranges", data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # range_14_16_EVT-XXXX
    m_range = re.match(r"^range_(?P<s>\d{1,2})_(?P<e>\d{1,2})_(?P<event>EVT-[A-Za-z0-9\-]+)$", selection)
    if m_range:
        start_h = int(m_range.group("s"))
        end_h   = int(m_range.group("e"))
        event_id = _clean_event_id(m_range.group("event"))
        _send_halves(to_number=from_number, start_hour=start_h, end_hour=end_h, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", f"sent: halves {start_h}-{end_h}", data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # slot_EVT-XXXX_14_00  (המקרה המועדף)
    m_slot = re.match(r"^slot_(?P<event>EVT-[A-Za-z0-9\-]+)_(?P<h>\d{1,2})_(?P<m>\d{2})$", selection)
    if m_slot:
        event_id = _clean_event_id(m_slot.group("event"))
        hh = int(m_slot.group("h"))
        mm = int(m_slot.group("m"))
        _update_time_by_event(event_id, hh, mm)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "incoming", event_id, to_number, from_number,
                        f"slot chosen {hh:02d}:{mm:02d}", button_text, button_payload, data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # --- מקרים חלופיים/סתם מספרים כמו "6" או "06" או "6:30" ---
    # אם הפיילוד הוא slot_EVT-XXXX והטייטל הוא שעה בלי נקודתיים וכו'
    m_slot_evt_only = re.match(r"^slot_(?P<event>EVT-[A-Za-z0-9\-]+)$", button_payload)
    if m_slot_evt_only:
        event_id = _clean_event_id(m_slot_evt_only.group("event"))
        title = list_title or button_text or body
        # תומך ב"6" -> 06:00, "06" -> 06:00, "6:30" -> 06:30, "06:30" -> 06:30
        m_hhmm = re.match(r"^\s*(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*$", title or "")
        if m_hhmm:
            hh = int(m_hhmm.group("h"))
            mm = int(m_hhmm.group("m") or 0)
            _update_time_by_event(event_id, hh, mm)
            try:
                ss = sheets.open_sheet()
                _append_log(ss, "incoming", event_id, to_number, from_number,
                            f"slot chosen {hh:02d}:{mm:02d}", button_text, button_payload, data)
            except Exception:
                pass
            return PlainTextResponse("OK", status_code=200)

    # Default: לא זוהה זרם — נחזיר OK (HTTP), זה לא נשלח לוואטסאפ
    return PlainTextResponse("OK", status_code=200)
