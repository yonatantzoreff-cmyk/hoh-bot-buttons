# app/routers/followups.py
import os
import re
import logging
import datetime
import pytz
from fastapi import APIRouter

from app.utils import sheets
from app.twilio_client import send_content_message  # שולח דרך Messaging Service בלבד
from app.utils import vault  # ← מחסן אנשי קשר (ContactsVault)

router = APIRouter()

TZ = os.getenv("TZ", "Asia/Jerusalem")
LOCAL_TZ = pytz.timezone(TZ)

# ---------- Helpers ----------

def _to_local_aware(dt: datetime.datetime) -> datetime.datetime:
    """הופך datetime ל-aware ב-Timezone המקומי."""
    if dt.tzinfo is None:
        return LOCAL_TZ.localize(dt)
    return dt.astimezone(LOCAL_TZ)

def _parse_due_iso(due_iso: str) -> datetime.datetime | None:
    """מקבל due כמחרוזת ומחזיר datetime aware בלוקאל."""
    s = (due_iso or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                break
            except Exception:
                dt = None
        if dt is None:
            logging.warning(f"[FOLLOWUPS] could not parse due string: {due_iso!r}")
            return None
    return _to_local_aware(dt)

def _normalize_phone(num: str) -> str:
    """הופך 05x… ל-whatsapp:+9725…  (Fallback אם אין יעד מה-Vault)."""
    num = (num or "").strip()
    if num.startswith("whatsapp:"):
        return num
    digits = re.sub(r"\D", "", num)
    if not digits:
        return ""
    if digits.startswith("972"):
        e164 = "+" + digits
    elif digits.startswith("0"):
        e164 = "+972" + digits[1:]
    elif digits.startswith("5"):
        e164 = "+972" + digits
    else:
        e164 = "+" + digits
    return f"whatsapp:{e164}"

# ---------- Route ----------

@router.post("/run_followups")
def run_followups():
    ss = sheets.open_sheet()
    ws = sheets.get_worksheet(ss, os.getenv("SHEET_EVENTS_NAME"))
    headers = sheets.get_headers(ws)

    id_idx    = sheets.find_col_index(headers, ["event_id", "id"])
    phone_idx = sheets.find_col_index(headers, ["supplier_phone", "phone", "טלפון"])
    name_idx  = sheets.find_col_index(headers, ["supplier_name", "name", "שם"])
    date_idx  = sheets.find_col_index(headers, ["event_date", "date", "תאריך"])
    time_idx  = sheets.find_col_index(headers, ["event_time", "show_time", "שעת מופע", "שעה"])
    show_idx  = sheets.find_col_index(headers, ["event_name", "show", "מופע"])
    due_idx   = sheets.find_col_index(headers, ["follow_up_due_at", "followup_due", "follow_up"])

    if None in [id_idx, phone_idx, name_idx, date_idx, show_idx, due_idx]:
        return {"ok": False, "error": "missing columns"}

    rows = ws.get_all_values()
    now_local = datetime.datetime.now(LOCAL_TZ)

    content_sid = os.getenv("CONTENT_SID_INIT_QR")
    if not content_sid:
        logging.warning("[FOLLOWUPS] CONTENT_SID_INIT_QR missing; followups will be skipped.")

    sent = 0

    for r_i in range(1, len(rows)):
        row = rows[r_i]
        if max(id_idx, phone_idx, name_idx, date_idx, show_idx, due_idx) >= len(row):
            continue

        due_iso = (row[due_idx] or "").strip()
        if not due_iso:
            continue
        due_local = _parse_due_iso(due_iso)
        if not due_local or due_local > now_local:
            continue

        # Build variables from row
        event_id = (row[id_idx] or "").strip()
        supplier_name = (row[name_idx] or "שלום").strip()
        show_name = (row[show_idx] or "").strip()
        event_date = (row[date_idx] or "").strip()
        event_time = (row[time_idx] or "").strip() if time_idx is not None and time_idx < len(row) else ""

        variables = {
            "1": supplier_name,
            "2": show_name,
            "3": event_date,
            "4": event_time,
            "5": event_id,
        }

        # יעד: קודם כל מה-Vault (מועדף להרכב), אם אין – fallback לספק
        to_wa, display_name = vault.choose_target_for_event(event_id)
        if to_wa:
            if display_name:
                variables["1"] = display_name
            to = to_wa
        else:
            to = _normalize_phone(row[phone_idx] or "")
            if not to:
                continue  # אין למי לשלוח

        if content_sid:
            try:
                send_content_message(to, content_sid, variables)
                sent += 1
            except Exception as e:
                logging.exception(f"[FOLLOWUPS] send_content_message failed for {to}: {e}")
        else:
            logging.info(f"[FOLLOWUPS] skipping send to {to}: no CONTENT_SID_INIT_QR")

        # נקה due כדי שלא יופעל שוב
        try:
            ws.update_cell(r_i + 1, due_idx + 1, "")
        except Exception as e:
            logging.exception(f"[FOLLOWUPS] failed to clear due cell at row {r_i+1}: {e}")

    return {"ok": True, "sent": sent}
