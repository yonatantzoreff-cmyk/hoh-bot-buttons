import os, datetime, pytz, json
from fastapi import APIRouter
from app.utils import sheets
from app.twilio_client import send_content_message, send_text

router = APIRouter()
TZ = os.getenv("TZ", "Asia/Jerusalem")

@router.post("/run_followups")
def run_followups():
    """Scan events with follow_up_due_at <= now and ping supplier again with INIT_QR."""
    ss = sheets.open_sheet()
    ws = sheets.get_worksheet(ss, os.getenv("SHEET_EVENTS_NAME"))
    headers = sheets.get_headers(ws)
    id_idx = sheets.find_col_index(headers, ["event_id","id"])
    phone_idx = sheets.find_col_index(headers, ["supplier_phone","phone","טלפון"])
    name_idx = sheets.find_col_index(headers, ["supplier_name","name","שם"])
    date_idx = sheets.find_col_index(headers, ["event_date","date","תאריך"])
    show_idx = sheets.find_col_index(headers, ["event_name","show","מופע"])
    due_idx = sheets.find_col_index(headers, ["follow_up_due_at","followup_due","follow_up"])
    if None in [id_idx, phone_idx, name_idx, date_idx, show_idx, due_idx]:
        return {"ok": False, "error":"missing columns"}
    rows = ws.get_all_values()
    tz = pytz.timezone(TZ)
    now = datetime.datetime.now(tz)
    sent = 0
    for r_i in range(1, len(rows)):
        row = rows[r_i]
        due_iso = row[due_idx]
        if not due_iso:
            continue
        try:
            due = tz.localize(datetime.datetime.fromisoformat(due_iso.replace("Z","")))
        except Exception:
            continue
        if due <= now:
            to = row[phone_idx]
            variables = {
                "1": row[name_idx] or "שלום",
                "2": row[date_idx],
                "3": row[show_idx],
                "4": row[id_idx],
            }
            sid = os.getenv("CONTENT_SID_INIT_QR")
            if sid:
                send_content_message(to, sid, variables)
                sent += 1
            else:
                send_text(to, f"היי {variables['1']}, תגיע בשעה כך וכך בתאריך {variables['2']} למופע {variables['3']}.")
            # Clear follow up to avoid spamming
            ws.update_cell(r_i+1, due_idx+1, "")
    return {"ok": True, "sent": sent}
