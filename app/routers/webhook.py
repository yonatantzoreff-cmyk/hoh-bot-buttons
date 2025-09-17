# app/routers/webhook.py
# Buttons-only MVP: WhatsApp Interactive -> Google Sheets (incl. Contacts Vault + contact handoff + back buttons)

from fastapi import APIRouter, Request
from fastapi.responses import Response
import logging, os, re, datetime, pytz, json

from app.utils import sheets
from app.utils import vault  # מחסן אנשי קשר
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
    """הערך המועיל ביותר: ButtonPayload > ListItemValue > ButtonText > ListItemTitle > Body"""
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

def _clean_event_id(value: str) -> str:
    """מחלץ EVT-XXXX מהטקסט; אם יש כפילויות EVT-EVT-… לוקח את האחרון."""
    if not value:
        return value
    matches = re.findall(r"EVT-[A-Za-z0-9\-]+", value)
    if matches:
        return matches[-1]
    return value.strip()

# פירוק מספרים
def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def _normalize_phone_last9(num: str) -> str:
    return _digits_only(num)[-9:]  # ישראל

# מאגר שדות אפשריים מאיש קשר
def _extract_contacts_from_text(text: str) -> list[dict]:
    """חילוץ אנשי קשר מטקסט חופשי. מחזיר [{"wa":"whatsapp:+9725...","name":None}, ...]"""
    if not text:
        return []
    pattern = re.compile(r"(?:\+972-?|972-?|0)(5\d)(?:[-\s]?\d){7}")
    out = []
    for m in pattern.finditer(text):
        raw = m.group(0)
        digits = _digits_only(raw)
        if digits.startswith("972"):
            e164 = f"+{digits}"
        elif digits.startswith("0"):
            e164 = f"+972{digits[1:]}"
        elif digits.startswith("5"):
            e164 = f"+972{digits}"
        else:
            continue
        out.append({"wa": f"whatsapp:{e164}", "name": None})
    # ייחוד
    uniq = []
    for c in out:
        if all(u["wa"] != c["wa"] for u in uniq):
            uniq.append(c)
    return uniq

def _extract_contacts_from_contacts_field(contacts_raw: str) -> list[dict]:
    """WhatsApp 'Share contact' → Twilio Contacts JSON. מחזיר [{"wa":..., "name":...}]"""
    if not contacts_raw:
        return []
    out = []
    try:
        obj = json.loads(contacts_raw)
        items = obj if isinstance(obj, list) else [obj]
        for it in items:
            name = (it.get("name") or it.get("display_name") or
                    (it.get("first_name","") + " " + it.get("last_name","")).strip() or None)
            wa_id = it.get("wa_id")
            if wa_id:
                out.append({"wa": f"whatsapp:+{_digits_only(str(wa_id))}", "name": name})
            for p in it.get("phones", []) or []:
                digits = _digits_only(p.get("phone") or "")
                if not digits:
                    continue
                if digits.startswith("972"):
                    e164 = f"+{digits}"
                elif digits.startswith("0"):
                    e164 = f"+972{digits[1:]}"
                elif digits.startswith("5"):
                    e164 = f"+972{digits}"
                else:
                    continue
                out.append({"wa": f"whatsapp:{e164}", "name": name})
    except Exception:
        pass
    # ייחוד
    uniq = []
    for c in out:
        if all(u["wa"] != c["wa"] for u in uniq):
            uniq.append(c)
    return uniq

# ========================
# Senders (Content Templates)
# ========================

def _send_ranges(to_number: str, event_id: str, variables: dict | None = None):
    """
    שולח תבנית ה-Ranges (List של טווחי שעתיים).
    בטמפלט: Item ID = range_06_08_{{5}}  (ללא הידבקות 'EVT-')
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
    תבנית Halves אחידה (4 פריטים): שמות {{t1..t4}}, IDs: slot_{{5}}_{{h1}}_{{m1}}, וכו׳
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
    vars_out["6"] = f"{start_hour:02d}:00–{end_hour:02d}:00"

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

def _send_init_to_number(to_whatsapp: str, event_id: str, contact_name: str | None = None):
    """שולח INIT_QR לאיש קשר (עם השם שלו אם קיים)."""
    sid = os.getenv("CONTENT_SID_INIT_QR")
    if not sid:
        logging.warning("Missing CONTENT_SID_INIT_QR; cannot send INIT to contact.")
        return
    evt = vault.get_event_row_by_id(_clean_event_id(event_id))
    supplier_name = "שלום"
    show_name = event_date = event_time = ""
    if evt:
        show_name  = evt.get("event_name", "")
        event_date = evt.get("event_date", "")
        event_time = evt.get("event_time", "")
    display_name = (contact_name or supplier_name or "שלום").strip()
    variables = {"1": display_name, "2": show_name, "3": event_date, "4": event_time, "5": _clean_event_id(event_id)}
    send_content_message(to_whatsapp, sid, variables)

def _send_main_menu(to_number: str, event_id: str):
    """שולח מחדש את תבנית התפריט הראשי (INIT_QR) לשולח."""
    if not os.getenv("CONTENT_SID_INIT_QR"):
        logging.warning("Missing CONTENT_SID_INIT_QR; cannot send main menu.")
        return
    _send_init_to_number(to_number, event_id)

# ========================
# Sheets writers
# ========================

def _update_time_by_event(event_id: str, hh: int, mm: int) -> bool:
    """כתיבת HH:MM לעמודת load_in_time + סטטוס."""
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
    """עדכון סטטוס בלבד (או עדכון ידני אם אין API מתאים)."""
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

    # לוג מפתחות + דוגמית
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
    contacts_raw = _get(data, "Contacts")  # אם שותף כרטיס איש קשר

    selection = _pick_interactive_value(data)
    logging.info(f"[WA IN] selection={selection!r}")

    # לוג לשונית ההודעות (incoming)
    try:
        ss = sheets.open_sheet()
        _append_log(ss, "incoming", "", to_number, from_number, body, button_text, button_payload, data)
    except Exception as e:
        logging.exception(f"[LOG] failed (initial append): {e}")

    # ----------------------------------------------------
    # 0) “לכידה אוניברסלית”: הגיע מספר/כרטיס איש קשר → שלח INIT אליו, עדכן Vault, רשום referral
    # ----------------------------------------------------
    contacts_from_field = _extract_contacts_from_contacts_field(contacts_raw) if contacts_raw else []
    contacts_from_text  = _extract_contacts_from_text(list_title or button_text or body)
    all_contacts = contacts_from_field or contacts_from_text

    if all_contacts:
        event_id = _resolve_event_id_for_phone(from_number)
        if event_id:
            evt = vault.get_event_row_by_id(event_id)
            org_name = (evt["event_name"] if evt else "").strip() or "Unknown"
            for c in all_contacts:
                wa = c.get("wa"); nm = c.get("name")
                if not wa:
                    continue
                phone_e164 = wa.replace("whatsapp:", "")
                first_name = vault.only_first_name(nm)  # אם אין שם – לא נוסיף
                # Vault: רשימת היסטוריה + הפוך למועדף (כלל 5b + 7b)
                vault.upsert_contact(org_name, event_id, phone_e164, first_name, source="not_contact", make_preferred=True)
                # רשום דניאל→ארז וכו׳
                vault.record_referral(org_name, from_number, wa, event_id)
                # שלח INIT אליו (עם שמו אם קיים)
                _send_init_to_number(wa, event_id, contact_name=first_name)
                # סטטוס + לוג
                _update_status_by_event(event_id, "handoff_to_contact")
                try:
                    ss = sheets.open_sheet()
                    _append_log(ss, "outgoing", event_id, wa, to_number,
                                f"auto-init to contact ({first_name or 'no-name'})", "", "sent: INIT to contact", data)
                except Exception:
                    pass
            return Response(status_code=200)

    # ----------------------------------------------------
    # 1) שכבת תאימות ל-Quick Reply ללא event_id בפיילוד
    # ----------------------------------------------------
    if (data.get("MessageType") == "button" and (button_payload or "").upper() == "CHOOSE_TIME"):
        event_id = _resolve_event_id_for_phone(from_number)
        if not event_id:
            logging.warning("[WA IN] CHOOSE_TIME but event_id not found for phone.")
            return Response(status_code=200)
        _send_ranges(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: ranges (from CHOOSE_TIME)", data)
        except Exception:
            pass
        return Response(status_code=200)

    if (data.get("MessageType") == "button" and (button_payload or "").upper() == "NOT_SURE"):
        event_id = _resolve_event_id_for_phone(from_number)
        if event_id:
            _send_not_sure(to_number=from_number, event_id=event_id)
            _update_status_by_event(event_id, "supplier_not_sure")
            try:
                ss = sheets.open_sheet()
                _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: not_sure", data)
            except Exception:
                pass
        return Response(status_code=200)

    if (data.get("MessageType") == "button" and (button_payload or "").upper() == "NOT_CONTACT"):
        event_id = _resolve_event_id_for_phone(from_number)
        if event_id:
            _send_contact(to_number=from_number, event_id=event_id)  # בקשה לשליחת איש קשר
            _update_status_by_event(event_id, "contact_required")
            try:
                ss = sheets.open_sheet()
                _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: contact_prompt", data)
            except Exception:
                pass
        return Response(status_code=200)

    # ----------------------------------------------------
    # 2) הזרימה הסטנדרטית עם event_id בפיילוד
    # ----------------------------------------------------

    # חזור לתפריט הראשי
    m_back_main = re.match(r"^back_to_main_(?P<event>EVT-[\w\-]+)$", selection)
    if m_back_main:
        event_id = _clean_event_id(m_back_main.group("event"))
        _send_main_menu(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: main_menu (back)", data)
        except Exception:
            pass
        return Response(status_code=200)

    # חזרה לטווחים
    m_back_rng = re.match(r"^back_to_ranges_(?P<event>EVT-[\w\-]+)$", selection)
    if m_back_rng:
        event_id = _clean_event_id(m_back_rng.group("event"))
        _send_ranges(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: ranges (back)", data)
        except Exception:
            pass
        return Response(status_code=200)

    # פתיחת טווחים מפורש
    m_open = re.match(r"^open_ranges_(?P<event>EVT-[A-Za-z0-9\-]+)$", selection)
    if m_open:
        event_id = _clean_event_id(m_open.group("event"))
        _send_ranges(to_number=from_number, event_id=event_id)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "outgoing", event_id, from_number, to_number, "", "", "sent: ranges", data)
        except Exception:
            pass
        return Response(status_code=200)

    # בחירת טווח שעתיים
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
        return Response(status_code=200)

    # בחירת חצי שעה (מועדף)
    m_slot = re.match(r"^slot_(?P<event>EVT-[A-Za-z0-9\-]+)_(?P<h>\d{1,2})_(?P<m>\d{2})$", selection)
    if m_slot:
        event_id = _clean_event_id(m_slot.group("event"))
        hh = int(m_slot.group("h"))
        mm = int(m_slot.group("m"))
        _update_time_by_event(event_id, hh, mm)
        # סימון הצלחה ב-Vault: מי שבחר (השולח) → preferred
        evt = vault.get_event_row_by_id(event_id)
        if evt:
            org_name = evt["event_name"]
            caller_phone_e164 = from_number.replace("whatsapp:", "")
            vault.mark_success(org_name, caller_phone_e164)
        try:
            ss = sheets.open_sheet()
            _append_log(ss, "incoming", event_id, to_number, from_number,
                        f"slot chosen {hh:02d}:{mm:02d}", button_text, button_payload, data)
        except Exception:
            pass
        return Response(status_code=200)

    # מקרה חלופי: Item ID = slot_EVT-xxxx אבל ה-Title/Body הוא שעה "6"/"06"/"6:30"
    m_slot_evt_only = re.match(r"^slot_(?P<event>EVT-[A-Za-z0-9\-]+)$", button_payload)
    if m_slot_evt_only:
        title = list_title or button_text or body
        m_hhmm = re.match(r"^\s*(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*$", title or "")
        if m_hhmm:
            event_id = _clean_event_id(m_slot_evt_only.group("event"))
            hh = int(m_hhmm.group("h"))
            mm = int(m_hhmm.group("m") or 0)
            _update_time_by_event(event_id, hh, mm)
            # סימון הצלחה ב-Vault
            evt = vault.get_event_row_by_id(event_id)
            if evt:
                org_name = evt["event_name"]
                caller_phone_e164 = from_number.replace("whatsapp:", "")
                vault.mark_success(org_name, caller_phone_e164)
            try:
                ss = sheets.open_sheet()
                _append_log(ss, "incoming", event_id, to_number, from_number,
                            f"slot chosen {hh:02d}:{mm:02d}", button_text, button_payload, data)
            except Exception:
                pass
            return Response(status_code=200)

    # ברירת מחדל: החזר 200 כדי שטוויליו לא יעשה ריטריי
    return Response(status_code=200)

# ========================
# Lookup by phone in Events
# ========================

def _resolve_event_id_for_phone(wa_from: str) -> str | None:
    """
    מאתר event_id בגיליון לפי מספר הספק (מהשורה של האירוע).
    עדיפות לסטטוסים 'ממתין' וכו׳ אם קיימים.
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
    want = _normalize_phone_last9(wa_from)
    candidates = []
    for r in rows[1:]:
        if max(phone_idx, event_idx) >= len(r):
            continue
        phone_cell = _normalize_phone_last9(r[phone_idx])
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
