import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import gspread
from google.oauth2.service_account import Credentials

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


logger = logging.getLogger(__name__)

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

def _header_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower())


def _require_sheet_name(env_key: str) -> str:
    value = os.getenv(env_key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {env_key}")
    return value


def _ensure_row_length(row: List[str], length: int) -> List[str]:
    """Pad a row list with empty strings up to the desired length."""
    if len(row) >= length:
        return row
    return row + ["" for _ in range(length - len(row))]


def list_events() -> List[Dict[str, str]]:
    """Return Events rows as dicts keyed by headers with string values and blanks for missing cells."""

    spreadsheet = open_sheet()
    sheet_name = _require_sheet_name("SHEET_EVENTS_NAME")
    worksheet = get_worksheet(spreadsheet, sheet_name)
    headers = get_headers(worksheet)
    normalized_headers = [_header_key(h) for h in headers]
    rows = worksheet.get_all_values()

    results: List[Dict[str, str]] = []
    for raw in rows[1:]:
        if not any((cell or "").strip() for cell in raw):
            continue
        padded = _ensure_row_length(list(raw), len(headers))
        row_dict: Dict[str, str] = {}
        for idx, header in enumerate(headers):
            value = padded[idx]
            if value is None:
                value = ""
            else:
                value = str(value)
            header_key = header or f"col_{idx}"
            row_dict[header_key] = value
            normalized = normalized_headers[idx] if idx < len(normalized_headers) else _header_key(header_key)
            if normalized:
                row_dict[normalized] = value
        results.append(row_dict)
    return results


def get_event_by_id(event_id: str) -> Optional[Dict[str, str]]:
    """Return a single event-row dict by event_id, or None if not found."""

    normalized_event_id = (event_id or "").strip()
    if not normalized_event_id:
        return None

    events = list_events()
    for row in events:
        if (row.get("event_id") or row.get("Event ID") or "").strip() == normalized_event_id:
            return row
    return None


def update_event(
    event_id: str,
    *,
    event_name: str,
    event_date: str,
    event_time: str,
    supplier_name: str,
    supplier_phone: str,
) -> bool:
    """Update row in Events sheet where event_id matches."""

    normalized_event_id = (event_id or "").strip()
    if not normalized_event_id:
        return False

    spreadsheet = open_sheet()
    sheet_name = _require_sheet_name("SHEET_EVENTS_NAME")
    worksheet = get_worksheet(spreadsheet, sheet_name)
    headers = get_headers(worksheet)
    header_map = {_header_key(h): idx for idx, h in enumerate(headers)}
    id_idx = header_map.get("event_id")
    if id_idx is None:
        logger.error("[SHEETS] Missing event_id column when updating event")
        return False

    rows = worksheet.get_all_values()
    total_columns = len(headers)
    for offset, raw in enumerate(rows[1:], start=2):
        padded = _ensure_row_length(list(raw), total_columns)
        if (padded[id_idx] or "").strip() != normalized_event_id:
            continue

        updates: Dict[int, str] = {}
        for key, value in (
            ("event_name", event_name),
            ("event_date", event_date),
            ("event_time", event_time),
            ("supplier_name", supplier_name),
            ("supplier_phone", supplier_phone),
        ):
            idx = header_map.get(key)
            if idx is not None:
                updates[idx] = value.strip()

        if not updates:
            return True

        for idx in sorted(updates.keys()):
            worksheet.update_cell(offset, idx + 1, updates[idx])
        return True

    return False


def delete_events_by_id(event_id: str) -> int:
    """Delete all rows in Events sheet where event_id equals."""

    normalized_event_id = (event_id or "").strip()
    if not normalized_event_id:
        return 0

    spreadsheet = open_sheet()
    sheet_name = _require_sheet_name("SHEET_EVENTS_NAME")
    worksheet = get_worksheet(spreadsheet, sheet_name)
    headers = get_headers(worksheet)
    header_map = {_header_key(h): idx for idx, h in enumerate(headers)}
    id_idx = header_map.get("event_id")
    if id_idx is None:
        logger.error("[SHEETS] Missing event_id column when deleting events")
        return 0

    rows = worksheet.get_all_values()
    delete_rows: List[int] = []
    for offset, raw in enumerate(rows[1:], start=2):
        if id_idx < len(raw) and (raw[id_idx] or "").strip() == normalized_event_id:
            delete_rows.append(offset)

    deleted = 0
    for row_number in sorted(delete_rows, reverse=True):
        worksheet.delete_rows(row_number)
        deleted += 1

    return deleted


def delete_referrals_by_event(event_id: str) -> int:
    """Delete all rows in ContactsReferrals sheet where event_id equals."""

    normalized_event_id = (event_id or "").strip()
    if not normalized_event_id:
        return 0

    spreadsheet = open_sheet()
    sheet_name = _require_sheet_name("SHEET_CONTACTS_REFERRALS_NAME")
    worksheet = get_worksheet(spreadsheet, sheet_name)
    headers = get_headers(worksheet)
    header_map = {_header_key(h): idx for idx, h in enumerate(headers)}
    event_idx = header_map.get("event_id")
    if event_idx is None:
        logger.warning("[SHEETS] Missing event_id column in ContactsReferrals when deleting")
        return 0

    rows = worksheet.get_all_values()
    delete_rows: List[int] = []
    for offset, raw in enumerate(rows[1:], start=2):
        if event_idx < len(raw) and (raw[event_idx] or "").strip() == normalized_event_id:
            delete_rows.append(offset)

    deleted = 0
    for row_number in sorted(delete_rows, reverse=True):
        worksheet.delete_rows(row_number)
        deleted += 1

    return deleted


def remove_event_from_vault(event_id: str) -> int:
    """Remove event_id from event_ids_json arrays in ContactsVault sheet."""

    normalized_event_id = (event_id or "").strip()
    if not normalized_event_id:
        return 0

    spreadsheet = open_sheet()
    sheet_name = _require_sheet_name("SHEET_CONTACTS_VAULT_NAME")
    worksheet = get_worksheet(spreadsheet, sheet_name)
    headers = get_headers(worksheet)
    header_map = {_header_key(h): idx for idx, h in enumerate(headers)}
    json_idx = header_map.get("event_ids_json")
    if json_idx is None:
        logger.warning("[SHEETS] Missing event_ids_json column in ContactsVault when removing event")
        return 0

    rows = worksheet.get_all_values()
    updated = 0
    for offset, raw in enumerate(rows[1:], start=2):
        if json_idx >= len(raw):
            continue
        raw_json = raw[json_idx] or ""
        if not raw_json.strip():
            continue
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("[SHEETS] Invalid JSON in event_ids_json for row %s", offset)
            continue
        if not isinstance(data, list):
            continue
        filtered = [item for item in data if item != normalized_event_id]
        if len(filtered) == len(data):
            continue
        new_json = json.dumps(filtered, separators=(",", ":"))
        worksheet.update_cell(offset, json_idx + 1, new_json)
        updated += 1

    return updated


def cascade_delete_event(event_id: str) -> Dict[str, int]:
    """Cascade delete event data across all sheets and return stats."""

    deleted_events = delete_events_by_id(event_id)
    deleted_referrals = delete_referrals_by_event(event_id)
    updated_vault_rows = remove_event_from_vault(event_id)
    return {
        "deleted_events": deleted_events,
        "deleted_referrals": deleted_referrals,
        "updated_vault_rows": updated_vault_rows,
    }


def append_message_log(spreadsheet, row: Dict[str, Any]):
    name = os.getenv("SHEET_MESSAGES_NAME")
    ws = get_worksheet(spreadsheet, name)
    headers = get_headers(ws)
    default_cols = ["timestamp", "direction", "event_id", "to", "from", "body", "button_text", "button_payload", "raw"]
    if not headers:
        ws.append_row([c for c in default_cols])
        headers = default_cols
    normalized = {_header_key(k): v for k, v in row.items()}
    values = [
        row.get(c, normalized.get(_header_key(c), ""))
        for c in headers
    ]
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

def update_event_supplier_phone(spreadsheet, event_id: str, phone_e164: str) -> bool:
    name = os.getenv("SHEET_EVENTS_NAME")
    ws = get_worksheet(spreadsheet, name)
    headers = get_headers(ws)
    id_idx = find_col_index(headers, ["event_id", "id", "Event ID"])
    phone_idx = find_col_index(headers, ["supplier_phone", "suplier_phone", "phone", "טלפון"])
    if id_idx is None or phone_idx is None:
        logging.warning("[SHEETS] missing event_id/supplier_phone columns when updating phone")
        return False
    rows = ws.get_all_values()
    for r_idx in range(1, len(rows)):
        row = rows[r_idx]
        if id_idx < len(row) and (row[id_idx] or "").strip() == event_id:
            ws.update_cell(r_idx + 1, phone_idx + 1, phone_e164)
            return True
    logging.info("[SHEETS] event_id %s not found when updating supplier phone", event_id)
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
