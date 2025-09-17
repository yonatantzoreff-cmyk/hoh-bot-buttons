# app/routers/webhook.py
# Buttons-only MVP: WhatsApp Interactive -> Google Sheets

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
import logging, os, re, datetime, pytz

from app.utils import sheets
from app.twilio_client import send_content_message  # שולח דרך Messaging Service בלבד

router = APIRouter()
TZ = os.getenv("TZ", "Asia/Jerusalem")

# ========================
# Utils & Helpers
# ========================

def now_iso() -> str:
    tz = pytz.timezone(TZ)
    return datetime.datetime.now(tz).isoformat()

def _get(d: dict, k: str) -> str:
    return (d.get(k) or "").strip()

def _pick_interactive_value(d: dict) -> str:
    """
    נחזיר את הערך המועיל ביותר מהאינטראקטיב:
    ButtonPayload > ListItemValue > ButtonText > ListItemTitle > Body
    """
    return (
        _get(d, "ButtonPayload")
        or _get(d, "ListItemValue")
        or _get(d, "ButtonText")
        or _get(d, "ListItemTitle")
        or _get(d, "Body")
    )

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

def _clean_event_id(value: str) -> str:
    """
    מחלץ מזהה אירוע תקין. אם הגיע 'EVT-EVT-10023' או טקסט ארוך –
    ניקח את ההופעה האחרונה של דפוס EVT-XXXX.
    """
    if not value:
        return value
    matches = re.findall(r"EVT-[A-Za-z0-9\-]+", value)
    if matches:
        return matches[-1]
    return value.strip()

def _normalize_phone(num: str) -> str:
    # שומר 9 ספרות אחרונות (מספיק לישראל), להסרת קידומות/תווים
    return re.sub(r"\D", "", num or "")[-9:]

def _resolve_event_id_for_phone(wa_from: str) -> str | None:
    """
    מאתר event_id בגיליון לפי מספר הספק.
    עדיפות לסטטוסים 'ממתין' וכד' אם קיימים.
    """
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
    for r in rows[1:]:
        if max(phone_idx, event_idx) >= len(r):
            continue
        phone_cell = _normalize_phone(r[phone_idx])
        if phone_cell == want:
            eid = (r[event_idx] or "").strip()
            st  = (r[status_idx] or "").strip().lower() if status_idx is not None and status_idx < len(r) else ""
            if eid:
                candidates.append((_clean_event_id(eid), st))

    if not candidates:
        logging.info(f"[SHEETS] no event found for phone {want}")
        return None

    preferred = {"waiting_load_in","pending","needs_time","ממתין","ממתין לשעת כניסה",""}
    for eid, st in candidates:
        if st in preferred:
            return eid
    return candidates[0][0]

# ========================
# Senders (Content Templates)
# ========================

def _send_ranges(to_number: str, event_id: str, variables: dict | None = None):
    """
    שולח תבנית ה-Ranges (List של טווחי שעתיים).
    ENV חובה: CONTENT_SID_RANGES
    בתבנית ה-Item ID צריך להיות: range_06_08_{{5}} (ללא הוספת 'EVT-')
    """
    sid = os.getenv("CONTENT_SID_RANGES")
    if not sid:
        logging.warning("Missing CONTENT_SID_RANGES; skipping send_ranges.")
        return
    vars_out = dict(variables or {})
    vars_out["5"] = _clean_event_id(event_id)
    send_content_message(to_number, sid, vars_out)

def _send_halves(to_number: str, start_hour: int, end_hour: int, event_id: str,
                 variables: dict | None = None):
    """
    שולח תבנית Halves אחידה (4 פריטים): t1..t4 לשם, h1/m1..h4/m4 ל-ID.
    ENV חובה: CONTENT_SID_HALVES
      בטמפלט: Item IDs כמו slot_{{5}}_{{h1}}_{{m1}}, ושמות {{t1}}...
    """
    sid = os.getenv("CONTENT_SID_HALVES")
    if not sid:
        logging.warning("Missing CONTENT_SID_HALVES; skipping send_halves.")
        return

    def hhmm(h: int, m: int) -> str:
        return f"{h:02d}:{m:02d}"

    slots = [(start_hour, 0), (start_hour, 30), (start_hour + 1, 0), (start_hour + 1, 30)]

    vars_out = dict(variables or {})
    vars_out["5"] = _clean_event_id(event_id)
    vars_out["6"] = f"{start_hour:02d}:00–{end_hour:02d}:00"  # תיאור הטווח (אם מוצג בכותרת/טקסט)

    for i, (hh, mm) in enumerate(slots, start=1):
        vars_out[f"t{i}"] = hhmm(hh, mm)
        vars_out[f"h{i}"] = f"{hh:02d}"
        vars_out[f"m{i}"] = f"{mm:02d}"

    send_content_message(to_number, sid, vars_out)

def _send_not_sure(to_number: str, event_id: str, variables: dict | None = None):
    sid = os.getenv("CONTENT_SID_NOT_SURE_QR")
    if not sid:
        logging.warning("Missing CONTENT_SID_NOT_SURE_QR; skipping send_not_sure.")
        return
    vars_out = dict(variables or {})
    vars_out["5"] = _clean_event_id(event_id)
    send_content_message(to_number, sid, vars_out)

def _send_contact(to_number: str, event_id: str, variables: dict | None = None):
    sid = os.getenv("CONTENT_SID_CONTACT_QR")
    if not sid:
        logging.warning("Missing CONTENT_SID_CONTACT_QR; skipping send_contact.")
        return
    vars_out = dict(variables or {})
    vars_out["5"] = _clean_event_id(event_id)
    send_content_message(to_number, sid, vars_out)

def _send_main_menu(to_number: str, event_id: str):
    """
    שולח מחדש את תבנית התפריט הראשי (INIT_QR).
    variables: 1=שם ספק, 2=שם מופע, 3=תאריך, 4=שעת מופע, 5=event_id
    """
    sid = os.getenv("CONTENT_SID_INIT_QR")
    if not sid:
        logging.warning("Missing CONTENT_SID_INIT_QR; cannot send main menu.")
        return

    ss = sheets.open_sheet()
    ws = sheets.get_worksheet(ss, os.getenv("SHEET_EVENTS_NAME"))
    headers = sheets.get_headers(ws)
    event_idx  = sheets.find_col_index(headers, ["event_id","Event ID","eventId"])
    name_idx   = sheets.find_col_index(headers, ["supplier_name","name","שם"])
    show_idx   = sheets.find_col_index(headers, ["event_name","show","מופע"])
    date_idx   = sheets.find_col_index(headers, ["event_date","date","תאריך"])
    time_idx   = sheets.find_col_index(headers, ["event_time","show_time","שעת מופע","שעה"])

    supplier_name = "שלום"
    show_name = event_date = event_time = ""
    eid = _clean_event_id(event_id)

    if event_idx is not None:
        rows = ws.get_all_values()
        for r in rows[1:]:
            if event_idx < len(r) and (r[event_idx] or "").strip() == eid:
                supplier_name = (r[name_idx] or "שלום").strip() if name_idx is not None and name_idx < len(r) else "שלום"
                show_name     = (r[show_idx] or "").strip() if show_idx is not None and show_idx < len(r) else ""
                event_date    = (r[date_idx] or "").strip() if date_idx is not None and date_idx < len(r) else ""
                event_time    = (r[time_idx] or "").strip() if time_idx is not None and time_idx < len(r) else ""
                break

    variables = {"1": supplier_name, "2": show_name, "3": event_date, "4": event_time, "5": eid}
    send_content_message(to_number, sid, variables)

# ========================
# Sheets writers
# ========================

def _update_time_by_event(event_id: str, hh: int, mm: int) -> bool:
    """
    כתיבת HH:MM לעמודת load_in_time + עדכון סטטוס.
    """
    ss = sheets.open_sheet()
    eid = _clean_event_id(event_id)
    time_str = f"{hh:02d}:{mm:02d}"
    try:
        ok = sheets.update_event_time(ss, eid, time_str, status="load_in_received")
        if not ok:
            logging.warning(f"[SHEETS] update_event_time returned False for {eid}")
        return ok
    except Exception as e:
        logging.exception(f"[SHEETS] update_event_time error: {e}")
        return False

def _update_status_by_event(event_id: str, status: str) -> bool:
    """
    עדכון סטטוס בלבד. מנסה דרך update_event_time(time=None),
    אחרת מבצע עדכון ידני לעמודת הסטטוס.
    """
    ss = sheets.open_sheet()
    eid = _clean_event_id(event_id)
    try:
        return sheets.update_event_time(ss, eid, None, status=status)  # type: ignore[arg-type]
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
                if event_idx < len(row) and (row[event_idx] or "").strip() == eid:
                    ws.update_cell(r_i + 1, status_idx + 1, status)
                    return True
            return False
        except Exception as e:
            logging.exception(f"[SHEETS] manual status update failed: {e}")
            return False
    except Exception as e:
        logging.exception(f"[SHEETS] update_status_by_event error: {e}")
        return False

# ========================
# Webhook
# ========================

@router.post("/whatsapp-webhook")
async def whatsapp_webhook(request: Request):
    # Twilio שולחת application/x-www-form-urlencoded
    form = await request.form()
    data = {k: form.get(k) for k in form.keys()}

    # לוג מפתחות + דוגמה
    try:
        logging.info("[WA IN] keys=%s sample=%s",
                     list(sorted(data.keys())),
                     {k: data[k] for k in list(sorted(data.keys()))[:10]})
    except Exception:
        pass

    from_number = _get(data, "From")    # whatsapp:+972...
    to_number   = _get(data, "To")      # whatsapp:+...
    body        = _get(data, "Body")
    button_text = _get(data, "ButtonText")
    button_payload = _get(data, "ButtonPayload")
    list_title  = _get(data, "ListItemTitle")
    list_value  = _get(data, "ListItemValue")

    selection = _pick_interactive_value(data)
    logging.info(f"[WA IN] selection={selection!r}")

    # לוג לשונית הודעות (incoming גולמי)
    try:
        ss = sheets.open_sheet()
        _append_log(ss, "incoming", "", to_number, from_number, body, button_text, button_payload, data)
    except Exception as e:
        logging.exception(f"[LOG] failed (initial append): {e}")

    # ----------------------------------------------------
    # שכבת תאימות ל-Quick Reply ישנים ללא event_id בפיילוד
    # ----------------------------------------------------

    # CHOOSE_TIME -> פותח טווחים
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

    # NOT_SURE -> תבנית אופציונלית + סטטוס
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

    # NOT_CONTACT -> תבנית אופציונלית + סטטוס
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

    # ----------------------------------------------------
    # הזרימה הסטנדרטית עם event_id בפיילוד
    # ----------------------------------------------------

    # back_to_main_EVT-xxxx  -> תפריט ראשי
    m_back_main = re.match(r"^back_to_main_(?P<event>EVT-[\w\-]+)$", selection)
    if m_back_main:
        event_id = _clean_event_id(m_back_main.group("event"))
        _send_main_menu(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: main_menu (back)", data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # back_to_ranges_EVT-xxxx -> חזרה לטווחים
    m_back_rng = re.match(r"^back_to_ranges_(?P<event>EVT-[\w\-]+)$", selection)
    if m_back_rng:
        event_id = _clean_event_id(m_back_rng.group("event"))
        _send_ranges(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: ranges (back)", data)
        except Exception:
            pass
        return PlainTextResponse("OK", status_code=200)

    # open_ranges_EVT-xxxx
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

    # range_06_08_EVT-xxxx
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

    # slot_EVT-xxxx_07_30 (מועדף)
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

    # מקרה חלופי: Item ID = slot_EVT-xxxx אבל ה-Title/Body הוא השעה "6" / "06" / "6:30"
    m_slot_evt_only = re.match(r"^slot_(?P<event>EVT-[A-Za-z0-9\-]+)$", button_payload)
    if m_slot_evt_only:
        title = list_title or button_text or body
        m_hhmm = re.match(r"^\s*(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*$", title or "")
        if m_hhmm:
            event_id = _clean_event_id(m_slot_evt_only.group("event"))
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

    # ברירת מחדל: לא זוהה זרם – נחזיר OK (HTTP) כדי שטוויליו לא יעשה ריטריי.
    return PlainTextResponse("OK", status_code=200)
