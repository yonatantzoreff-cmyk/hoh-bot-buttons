# app/utils/vault.py
import os, re, json, datetime, pytz, logging
from typing import Optional, Tuple, Dict, Any, List
from app.utils import sheets

TZ = os.getenv("TZ", "Asia/Jerusalem")
LOCAL_TZ = pytz.timezone(TZ)

SHEET_EVENTS_NAME  = os.getenv("SHEET_EVENTS_NAME")
SHEET_VAULT_NAME   = os.getenv("SHEET_CONTACTS_VAULT_NAME", "ContactsVault")
SHEET_EDGES_NAME   = os.getenv("SHEET_CONTACTS_REFERRALS_NAME", "ContactsReferrals")

# ---------- Normalizers ----------

def now_iso() -> str:
    return datetime.datetime.now(LOCAL_TZ).isoformat()

def norm_phone_e164_il(text: str) -> Optional[str]:
    """מחזיר +9725... (E.164) או None אם לא זוהה."""
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if digits.startswith("972"):
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+972{digits[1:]}"
    if digits.startswith("5"):
        return f"+972{digits}"
    return None

def only_first_name(name: Optional[str]) -> Optional[str]:
    """החזר שם פרטי בלבד; אם אין, החזר None."""
    if not name:
        return None
    # נקה אמוג'י וניקוד בסיסי
    s = re.sub(r"[\u0591-\u05C7]", "", name).strip()
    # פצל לרווח/מפריד — קח ראשון
    parts = re.split(r"[\s,|/]+", s)
    return parts[0] if parts and parts[0] else None

def canon_org_key(raw: str) -> str:
    """
    מפתח קנוני לשם ההרכב/ההפקה:
    - lowercase
    - הסרת סימני פיסוק, רווחים מרובים
    - תואם 'fuzzy' קל לפי מה שבחרת
    """
    s = (raw or "").lower()
    s = re.sub(r"[^\w\u0590-\u05FF]+", " ", s)  # תווים לא אות/ספרה/עברית -> רווח
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ---------- Sheet Helpers ----------

def _open_ws(name: str):
    ss = sheets.open_sheet()
    return sheets.get_worksheet(ss, name)

def _headers(ws):
    return sheets.get_headers(ws)

def _col(headers, aliases: List[str]) -> Optional[int]:
    return sheets.find_col_index(headers, aliases)

# ---------- Events lookup ----------

def get_event_row_by_id(event_id: str) -> Optional[Dict[str, Any]]:
    """מחזיר dict של שדות מה-Events לפי event_id, או None אם לא נמצא."""
    if not SHEET_EVENTS_NAME:
        logging.warning("[VAULT] SHEET_EVENTS_NAME missing")
        return None
    ws = _open_ws(SHEET_EVENTS_NAME)
    headers = _headers(ws)
    e_col = _col(headers, ["event_id","Event ID","eventId"])
    name_col = _col(headers, ["event_name","show","מופע"])
    date_col = _col(headers, ["event_date","date","תאריך"])
    time_col = _col(headers, ["event_time","show_time","שעת מופע","שעה"])
    if e_col is None or name_col is None:
        return None
    rows = ws.get_all_values()
    for r in rows[1:]:
        if e_col < len(r) and (r[e_col] or "").strip() == event_id:
            return {
                "event_id": (r[e_col] or "").strip(),
                "event_name": (r[name_col] or "").strip(),
                "event_date": (r[date_col] or "").strip() if date_col is not None and date_col < len(r) else "",
                "event_time": (r[time_col] or "").strip() if time_col is not None and time_col < len(r) else "",
            }
    return None

# ---------- Vault core ----------

def upsert_contact(org_display_name: str, event_id: Optional[str], phone_e164: str,
                   name_first: Optional[str], source: str, make_preferred: bool,
                   extra_event_ids: Optional[List[str]] = None) -> None:
    """
    מוסיף/מעדכן איש קשר למחסן:
    - לא דורס רשומות קיימות; מעדכן first_seen/last_seen/seen_count
    - אם make_preferred=True -> מסיר preferred מאחרים ומסמן רשומה זו כ-preferred
    - מוסיף event_id ל-event_ids_json (סט) אם קיים
    """
    if not phone_e164:
        return
    org_key = canon_org_key(org_display_name)
    ws = _open_ws(SHEET_VAULT_NAME)
    headers = _headers(ws)

    i_org_key   = _col(headers, ["org_key"])
    i_org_name  = _col(headers, ["org_display_name"])
    i_phone     = _col(headers, ["phone_e164"])
    i_name      = _col(headers, ["name_first"])
    i_pref      = _col(headers, ["preferred"])
    i_last_succ = _col(headers, ["last_success_at"])
    i_first     = _col(headers, ["first_seen_at"])
    i_last      = _col(headers, ["last_seen_at"])
    i_count     = _col(headers, ["seen_count"])
    i_src       = _col(headers, ["sources_json"])
    i_eids      = _col(headers, ["event_ids_json"])

    rows = ws.get_all_values()
    # חפש רשומה קיימת עבור org_key + phone
    found_idx = None
    for idx in range(1, len(rows)):
        r = rows[idx]
        if max(i_org_key, i_phone) >= len(r): 
            continue
        if (r[i_org_key] or "").strip() == org_key and (r[i_phone] or "").strip() == phone_e164:
            found_idx = idx
            break

    now = now_iso()
    def read_json_cell(cell: str) -> List[Any]:
        try:
            obj = json.loads(cell) if cell else []
            return obj if isinstance(obj, list) else []
        except Exception:
            return []

    if found_idx is None:
        # הוסף שורה חדשה
        seen_count = 1
        srcs = [source] if source else []
        eids = list(set([eid for eid in ([event_id] + (extra_event_ids or [])) if eid]))
        ws.append_row([
            org_key, org_display_name, phone_e164, (name_first or ""), 
            "TRUE" if make_preferred else "", "",  # preferred, last_success_at
            now, now, seen_count, json.dumps(srcs, ensure_ascii=False), json.dumps(eids, ensure_ascii=False)
        ])
    else:
        # עדכון שורה קיימת
        r = rows[found_idx]
        # org_display_name – נעדכן אם ריק
        if i_org_name is not None and (i_org_name < len(r)) and not (r[i_org_name] or "").strip():
            ws.update_cell(found_idx + 1, i_org_name + 1, org_display_name)
        # name_first – נעדכן אם הגיע חדש ולא ריק
        if name_first and i_name is not None and i_name < len(r):
            ws.update_cell(found_idx + 1, i_name + 1, name_first)
        # last_seen + count
        if i_last is not None:
            ws.update_cell(found_idx + 1, i_last + 1, now)
        if i_count is not None:
            try:
                curr = int((r[i_count] or "0").strip() or 0)
            except Exception:
                curr = 0
            ws.update_cell(found_idx + 1, i_count + 1, curr + 1)
        # sources_json
        if i_src is not None and i_src < len(r):
            srcs = read_json_cell(r[i_src])
            if source and source not in srcs:
                srcs.append(source)
            ws.update_cell(found_idx + 1, i_src + 1, json.dumps(srcs, ensure_ascii=False))
        # event_ids_json
        if i_eids is not None and i_eids < len(r):
            eids = read_json_cell(r[i_eids])
            for eid in [event_id] + (extra_event_ids or []):
                if eid and eid not in eids:
                    eids.append(eid)
            ws.update_cell(found_idx + 1, i_eids + 1, json.dumps(eids, ensure_ascii=False))
        # preferred
        if make_preferred and i_pref is not None:
            # נוריד preferred מאחרים ונרים לרשומה זו
            for j in range(1, len(rows)):
                row = rows[j]
                if max(i_org_key, i_pref) >= len(row): 
                    continue
                if (row[i_org_key] or "").strip() == org_key:
                    ws.update_cell(j + 1, i_pref + 1, "TRUE" if j == found_idx else "")
    # אם הפכנו למועדף ונרצה לאפס אחרים – כבר עשינו בלופ

def mark_success(org_display_name: str, phone_e164: str) -> None:
    """מסמן שהטלפון הזה הצליח (קיבל/סגר שעה) -> preferred=TRUE + last_success_at=now."""
    org_key = canon_org_key(org_display_name)
    ws = _open_ws(SHEET_VAULT_NAME)
    headers = _headers(ws)
    i_org_key = _col(headers, ["org_key"])
    i_phone   = _col(headers, ["phone_e164"])
    i_pref    = _col(headers, ["preferred"])
    i_last_s  = _col(headers, ["last_success_at"])
    rows = ws.get_all_values()
    now = now_iso()
    for idx in range(1, len(rows)):
        r = rows[idx]
        if max(i_org_key, i_phone) >= len(r): 
            continue
        if (r[i_org_key] or "").strip() == org_key and (r[i_phone] or "").strip() == phone_e164:
            if i_pref is not None:
                ws.update_cell(idx + 1, i_pref + 1, "TRUE")
            if i_last_s is not None:
                ws.update_cell(idx + 1, i_last_s + 1, now)
        elif (r[i_org_key] or "").strip() == org_key and i_pref is not None:
            # בטל preferred לאחרים
            ws.update_cell(idx + 1, i_pref + 1, "")

def record_referral(org_display_name: str, from_phone: str, to_phone: str, event_id: Optional[str]):
    """שומר קשת דניאל→ארז בספר 'ContactsReferrals'."""
    ws = _open_ws(SHEET_EDGES_NAME)
    ws.append_row([canon_org_key(org_display_name), from_phone, to_phone, event_id or "", now_iso()])

def choose_target_for_event(event_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    מחזיר יעד לשליחה (whatsapp:+972...) ושם תצוגה מועדף לפי ה-Vault.
    אם אין – החזר None,None.
    """
    evt = get_event_row_by_id(event_id)
    if not evt:
        return None, None
    org_key = canon_org_key(evt["event_name"])
    org_display = evt["event_name"]
    ws = _open_ws(SHEET_VAULT_NAME)
    headers = _headers(ws)
    i_org_key = _col(headers, ["org_key"])
    i_phone   = _col(headers, ["phone_e164"])
    i_name    = _col(headers, ["name_first"])
    i_pref    = _col(headers, ["preferred"])
    rows = ws.get_all_values()

    # חפש preferred קודם
    for r in rows[1:]:
        if max(i_org_key, i_phone, i_pref) >= len(r): 
            continue
        if (r[i_org_key] or "").strip() == org_key and (r[i_pref] or "").strip().upper() == "TRUE":
            phone = (r[i_phone] or "").strip()
            name  = (r[i_name] or "").strip() if i_name is not None and i_name < len(r) else ""
            return f"whatsapp:{phone}", (name or None)

    # אם אין preferred — בחר את זה עם last_success_at הכי חדש, אחרת הראשון
    i_last_s = _col(headers, ["last_success_at"])
    best_idx = None; best_ts = ""
    for idx in range(1, len(rows)):
        r = rows[idx]
        if max(i_org_key, i_phone) >= len(r): 
            continue
        if (r[i_org_key] or "").strip() == org_key:
            ts = (r[i_last_s] or "") if (i_last_s is not None and i_last_s < len(r)) else ""
            if ts > best_ts:
                best_ts, best_idx = ts, idx
            if best_idx is None:
                best_idx = idx
    if best_idx:
        rr = rows[best_idx]
        phone = (rr[i_phone] or "").strip()
        name  = (rr[i_name] or "").strip() if i_name is not None and i_name < len(rr) else ""
        return f"whatsapp:{phone}", (name or None)

    return None, None
