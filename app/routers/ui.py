"""Minimal Bootstrap-based UI for managing events."""
import logging
import os
import re
from html import escape
from typing import List
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.utils import sheets
from app.twilio_client import send_content_message as send_content

router = APIRouter()
logger = logging.getLogger(__name__)


def _header_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower())


def _clean_event_id(value: str) -> str:
    if not value:
        return value
    matches = re.findall(r"EVT-[A-Za-z0-9\-]+", value)
    if matches:
        return matches[-1]
    return value.strip()


def _normalize_phone(num: str) -> str:
    num = (num or "").strip()
    if not num:
        return ""
    if num.startswith("whatsapp:"):
        return num
    digits = re.sub(r"\D", "", num)
    if not digits:
        return ""
    if digits.startswith("972"):
        e164 = f"+{digits}"
    elif digits.startswith("0"):
        e164 = f"+972{digits[1:]}"
    elif digits.startswith("5"):
        e164 = f"+972{digits}"
    else:
        e164 = f"+{digits}"
    return f"whatsapp:{e164}"


def _render_page(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <title>{escape(title)}</title>
        <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\" rel=\"stylesheet\" integrity=\"sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH\" crossorigin=\"anonymous\">
      </head>
      <body class=\"bg-light\">
        <nav class=\"navbar navbar-expand-lg navbar-dark bg-dark\">
          <div class=\"container-fluid\">
            <a class=\"navbar-brand\" href=\"/ui\">HOH BOT – Events</a>
            <div>
              <a class=\"btn btn-outline-light btn-sm me-2\" href=\"/ui\">Add Event</a>
              <a class=\"btn btn-outline-light btn-sm\" href=\"/ui/events\">View Events</a>
            </div>
          </div>
        </nav>
        <main class=\"container py-4\">
          {body}
        </main>
      </body>
    </html>
    """


@router.get("/ui", response_class=HTMLResponse)
async def show_form() -> HTMLResponse:
    card = """
    <div class=\"row justify-content-center\">
      <div class=\"col-lg-6\">
        <div class=\"card shadow-sm\">
          <div class=\"card-header bg-primary text-white\">Add New Event</div>
          <div class=\"card-body\">
            <form method=\"post\" action=\"/ui/add_event\">
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"event_name\">Event name</label>
                <input class=\"form-control\" id=\"event_name\" name=\"event_name\" type=\"text\" required>
              </div>
              <div class=\"row\">
                <div class=\"col-md-6 mb-3\">
                  <label class=\"form-label\" for=\"event_date\">Event date</label>
                  <input class=\"form-control\" id=\"event_date\" name=\"event_date\" type=\"date\" required>
                </div>
                <div class=\"col-md-6 mb-3\">
                  <label class=\"form-label\" for=\"event_time\">Event time</label>
                  <input class=\"form-control\" id=\"event_time\" name=\"event_time\" type=\"time\" required>
                </div>
              </div>
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"supplier_name\">Supplier name</label>
                <input class=\"form-control\" id=\"supplier_name\" name=\"supplier_name\" type=\"text\" required>
              </div>
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"supplier_phone\">Supplier phone</label>
                <input class=\"form-control\" id=\"supplier_phone\" name=\"supplier_phone\" type=\"text\" required>
              </div>
              <div class=\"d-grid\">
                <button class=\"btn btn-primary\" type=\"submit\">Add Event</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
    """
    html = _render_page("Add Event", card)
    return HTMLResponse(content=html)


def _next_event_id(existing_ids: List[str]) -> str:
    max_num = 0
    pattern = re.compile(r"EVT-(\d+)")
    for value in existing_ids:
        if not value:
            continue
        match = pattern.search(value)
        if match:
            try:
                num = int(match.group(1))
                max_num = max(max_num, num)
            except ValueError:
                continue
    return f"EVT-{max_num + 1:04d}"


@router.post("/ui/add_event")
async def add_event(
    event_name: str = Form(...),
    event_date: str = Form(...),
    event_time: str = Form(...),
    supplier_name: str = Form(...),
    supplier_phone: str = Form(...),
):
    ss = sheets.open_sheet()
    events_name = os.getenv("SHEET_EVENTS_NAME")
    if not events_name:
        raise HTTPException(status_code=500, detail="SHEET_EVENTS_NAME env var is not set")
    ws = sheets.get_worksheet(ss, events_name)
    headers = sheets.get_headers(ws)
    header_map = {_header_key(h): idx for idx, h in enumerate(headers)}

    required_keys = [
        "event_id",
        "event_name",
        "event_date",
        "event_time",
        "supplier_name",
        "supplier_phone",
        "status",
    ]
    for key in required_keys:
        if key not in header_map:
            raise HTTPException(status_code=500, detail=f"Missing column in Events sheet: {key}")

    rows = ws.get_all_values()
    existing_ids = []
    id_idx = header_map["event_id"]
    for row in rows[1:]:
        if id_idx < len(row):
            existing_ids.append(row[id_idx])
    new_event_id = _next_event_id(existing_ids)

    new_row = ["" for _ in headers]
    new_row[header_map["event_id"]] = new_event_id
    new_row[header_map["event_name"]] = event_name.strip()
    new_row[header_map["event_date"]] = event_date.strip()
    new_row[header_map["event_time"]] = event_time.strip()
    new_row[header_map["supplier_name"]] = supplier_name.strip()
    new_row[header_map["supplier_phone"]] = supplier_phone.strip()
    new_row[header_map["status"]] = "pending"

    try:
        ws.append_row(new_row)
    except Exception as exc:
        logger.exception("Failed to append event row: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to add event") from exc

    return RedirectResponse(url="/ui/events", status_code=303)


@router.get("/ui/events", response_class=HTMLResponse)
async def list_events() -> HTMLResponse:
    ss = sheets.open_sheet()
    events_name = os.getenv("SHEET_EVENTS_NAME")
    if not events_name:
        raise HTTPException(status_code=500, detail="SHEET_EVENTS_NAME env var is not set")
    ws = sheets.get_worksheet(ss, events_name)
    headers = sheets.get_headers(ws)
    rows = ws.get_all_values()

    header_map = {_header_key(h): idx for idx, h in enumerate(headers)}

    required_keys = [
        "event_id",
        "event_name",
        "event_date",
        "event_time",
        "supplier_name",
        "supplier_phone",
        "status",
    ]
    missing = [k for k in required_keys if k not in header_map]
    if missing:
        body = (
            "<div class=\"alert alert-danger\" role=\"alert\">"
            f"Missing columns in Events sheet: {', '.join(missing)}"
            "</div>"
        )
        html = _render_page("Events", body)
        return HTMLResponse(content=html, status_code=500)

    table_rows: List[str] = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        event_id = row[header_map.get("event_id", 0)] if header_map.get("event_id") is not None and header_map["event_id"] < len(row) else ""
        name = row[header_map.get("event_name", 0)] if header_map.get("event_name") is not None and header_map["event_name"] < len(row) else ""
        date = row[header_map.get("event_date", 0)] if header_map.get("event_date") is not None and header_map["event_date"] < len(row) else ""
        time = row[header_map.get("event_time", 0)] if header_map.get("event_time") is not None and header_map["event_time"] < len(row) else ""
        supplier = row[header_map.get("supplier_name", 0)] if header_map.get("supplier_name") is not None and header_map["supplier_name"] < len(row) else ""
        phone = row[header_map.get("supplier_phone", 0)] if header_map.get("supplier_phone") is not None and header_map["supplier_phone"] < len(row) else ""
        status = row[header_map.get("status", 0)] if header_map.get("status") is not None and header_map["status"] < len(row) else ""

        event_id_display = escape(event_id)
        run_url = f"/ui/run_event/{quote(event_id)}"
        button = ""
        if event_id:
            button = (
                f"<form method=\"post\" action=\"{run_url}\" class=\"d-inline\">"
                f"<button class=\"btn btn-sm btn-outline-primary\" type=\"submit\">Send INIT</button>"
                "</form>"
            )

        table_rows.append(
            """
            <tr>
              <td>{event_id}</td>
              <td>{name}</td>
              <td>{date}</td>
              <td>{time}</td>
              <td>{supplier}</td>
              <td>{phone}</td>
              <td>{status}</td>
              <td>{button}</td>
            </tr>
            """.format(
                event_id=event_id_display,
                name=escape(name),
                date=escape(date),
                time=escape(time),
                supplier=escape(supplier),
                phone=escape(phone),
                status=escape(status),
                button=button,
            )
        )

    table_body = "".join(table_rows) or """
        <tr>
          <td colspan=\"8\" class=\"text-center text-muted\">No events yet.</td>
        </tr>
    """

    table = f"""
    <div class=\"card\">
      <div class=\"card-header bg-secondary text-white\">Events</div>
      <div class=\"card-body\">
        <div class=\"table-responsive\">
          <table class=\"table table-striped align-middle\">
            <thead>
              <tr>
                <th scope=\"col\">Event ID</th>
                <th scope=\"col\">Name</th>
                <th scope=\"col\">Date</th>
                <th scope=\"col\">Time</th>
                <th scope=\"col\">Supplier</th>
                <th scope=\"col\">Phone</th>
                <th scope=\"col\">Status</th>
                <th scope=\"col\"></th>
              </tr>
            </thead>
            <tbody>
              {table_body}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """

    html = _render_page("Events", table)
    return HTMLResponse(content=html)


@router.post("/ui/run_event/{event_id}")
async def run_event(event_id: str):
    ss = sheets.open_sheet()
    events_name = os.getenv("SHEET_EVENTS_NAME")
    if not events_name:
        raise HTTPException(status_code=500, detail="SHEET_EVENTS_NAME env var is not set")
    ws = sheets.get_worksheet(ss, events_name)
    headers = sheets.get_headers(ws)
    header_map = {_header_key(h): idx for idx, h in enumerate(headers)}

    id_idx = header_map.get("event_id")
    phone_idx = header_map.get("supplier_phone")
    name_idx = header_map.get("supplier_name")
    event_name_idx = header_map.get("event_name")

    if id_idx is None or phone_idx is None or name_idx is None or event_name_idx is None:
        raise HTTPException(status_code=500, detail="Missing columns in Events sheet")

    rows = ws.get_all_values()
    supplier_phone = ""
    supplier_name = ""
    event_name = ""
    for row in rows[1:]:
        if id_idx < len(row) and (row[id_idx] or "").strip() == event_id:
            supplier_phone = row[phone_idx] if phone_idx < len(row) else ""
            supplier_name = row[name_idx] if name_idx < len(row) else ""
            event_name = row[event_name_idx] if event_name_idx < len(row) else ""
            break

    if not supplier_phone:
        raise HTTPException(status_code=404, detail="Event not found or missing phone")

    to = _normalize_phone(supplier_phone)
    if not to:
        raise HTTPException(status_code=400, detail="Supplier phone is invalid")

    content_sid = os.getenv("CONTENT_SID_INIT_QR")
    if not content_sid:
        raise HTTPException(status_code=500, detail="Missing CONTENT_SID_INIT_QR env var")

    variables = {
        "1": supplier_name or "",
        "2": event_name or "",

        "1": event_name or "",
        "2": supplier_name or "",

        "5": _clean_event_id(event_id),
    }

    try:
        send_content(to, content_sid, variables)
    except Exception as exc:
        logger.exception("Failed to send INIT content for %s: %s", event_id, exc)
        raise HTTPException(status_code=500, detail="Failed to send INIT message") from exc

    return RedirectResponse(url="/ui/events", status_code=303)
