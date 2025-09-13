import os, json, base64
from typing import Dict, Any, List, Optional
import gspread
from google.oauth2.service_account import Credentials

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _load_creds():
    b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
    path = os.getenv("GOOGLE_CREDENTIALS_FILE")
    if b64:
        data = base64.b64decode(b64)
        return Credentials.from_service_account_info(json.loads(data), scopes=SCOPE)
    if path and os.path.exists(path):
        return Credentials.from_service_account_file(path, scopes=SCOPE)
    raise RuntimeError("Missing Google credentials. Set GOOGLE_CREDENTIALS_FILE or GOOGLE_CREDENTIALS_B64")

def get_client() -> gspread.Client:
    creds = _load_creds()
    return gspread.authorize(creds)

def open_sheet():
    gc = get_client()
    spreadsheet_key = os.getenv("SPREADSHEET_KEY")
    if spreadsheet_key:
        return gc.open_by_key(spreadsheet_key)
    return gc.open(os.getenv("SHEET_EVENTS_NAME"))

def get_worksheet(spreadsheet, name: str):
    try:
        return spreadsheet.worksheet(name)
    except Exception:
        try:
            gc = get_client()
            ss = gc.open(name)
            return ss.get_worksheet(0)
        except Exception:
            raise

def get_headers(ws) -> List[str]:
    values = ws.row_values(1)
    return [h.strip() for h in values]

def find_col_index(headers: List[str], wanted: List[str]) -> Optional[int]:
    for i, h in enumerate(headers):
        key = h.strip().lower()
        if key in [w.lower() for w in wanted]:
            return i
    return None

def append_message_log(spreadsheet, row: Dict[str, Any]):
    name = os.getenv("SHEET_MESSAGES_NAME")
    ws = get_worksheet(spreadsheet, name)
    headers = get_headers(ws)
    default_cols = ["timestamp", "direction", "event_id", "to", "from", "body", "button_text", "button_payload", "raw"]
    if not headers:
        ws.append_row([c for c in default_cols])
        headers = default_cols
    values = [row.get(c, "") for c in headers]
    ws.append_row(values)

def update_event_time(spreadsheet, event_id: str, time_str: str, status: str = "confirmed") -> bool:
    name = os.getenv("SHEET_EVENTS_NAME")
    ws = get_worksheet(spreadsheet, name)
    headers = get_headers(ws)
    id_idx = find_col_index(headers, ["event_id", "id", "Event ID"])
    time_idx = find_col_index(headers, ["load_in_time", "load-in time", "load_in", "כניסה", "שעת כניסה"])
    status_idx = find_col_index(headers, ["status", "Status"])
    if id_idx is None:
        raise RuntimeError("Could not find 'event_id' column in events sheet")
    rows = ws.get_all_values()
    for r_idx in range(1, len(rows)):
        if rows[r_idx][id_idx] == event_id:
            if time_idx is not None:
                ws.update_cell(r_idx+1, time_idx+1, time_str)
            if status_idx is not None:
                ws.update_cell(r_idx+1, status_idx+1, status)
            return True
    return False

def set_followup_due(spreadsheet, event_id: str, due_iso: str):
    name = os.getenv("SHEET_EVENTS_NAME")
    ws = get_worksheet(spreadsheet, name)
    headers = get_headers(ws)
    id_idx = find_col_index(headers, ["event_id", "id"])
    due_idx = find_col_index(headers, ["follow_up_due_at", "followup_due", "follow_up"])
    status_idx = find_col_index(headers, ["status"])
    if id_idx is None:
        raise RuntimeError("Could not find 'event_id' column in events sheet")
    if due_idx is None:
        ws.update_cell(1, len(headers)+1, "follow_up_due_at")
        due_idx = len(headers)
    rows = ws.get_all_values()
    for r_idx in range(1, len(rows)):
        if rows[r_idx][id_idx] == event_id:
            ws.update_cell(r_idx+1, due_idx+1, due_iso)
            if status_idx is not None:
                ws.update_cell(r_idx+1, status_idx+1, "awaiting_supplier")
            return True
    return False
