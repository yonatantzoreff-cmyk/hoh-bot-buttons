"""Minimal Bootstrap-based UI for managing events via Postgres."""
import logging
from typing import Optional
from datetime import datetime, timezone
from html import escape
from string import Template
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import twilio_client
from app.credentials import CONTENT_SID_SHIFT_REMINDER
from app.dependencies import get_hoh_service
from app.hoh_service import HOHService
from app.utils.phone import normalize_phone_to_e164_il
from app.time_utils import (
    get_il_tz,
    utc_to_local_datetime,
    utc_to_local_time_str,
    format_datetime_for_display,
    parse_datetime_local_input,
)

router = APIRouter()
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")

ISRAEL_TZ = get_il_tz()


def _datetime_to_time_str(dt):
    """
    Convert a datetime from DB (UTC) to local time string for display.
    
    This replaces the old _strip_timezone which was causing the bug
    where times would shift by 2 hours on edit.
    """
    if not dt:
        return None
    
    # Convert UTC datetime to Israel local time string (HH:MM)
    return utc_to_local_time_str(dt)


def _to_israel_time(dt):
    """Convert a timestamp (assumed UTC if naive) to Israel time."""
    if not dt:
        return None
    
    # Use centralized utility
    return utc_to_local_datetime(dt)


def _render_page(title: str, body: str) -> str:
    page = Template(
        """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>$title</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">
        <link href="https://cdn.datatables.net/1.13.8/css/dataTables.bootstrap5.min.css" rel="stylesheet">
        <link href="https://cdn.datatables.net/colreorder/1.6.3/css/colReorder.bootstrap5.min.css" rel="stylesheet">
      </head>
      <body class="bg-light">
        <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
          <div class="container-fluid">
            <a class="navbar-brand" href="/ui">HOH BOT – Events</a>
            <div>
              <a class="btn btn-outline-light btn-sm me-2" href="/ui">Add Event</a>
              <a class="btn btn-outline-light btn-sm" href="/ui/events">View Events</a>
              <a class="btn btn-outline-light btn-sm ms-2" href="/ui/contacts">Contacts</a>
              <a class="btn btn-outline-light btn-sm ms-2" href="/ui/employees">Employees</a>
              <a class="btn btn-light btn-sm ms-2" href="/ui/messages">Messages</a>
              <a class="btn btn-outline-success btn-sm ms-2" href="/ui/calendar-import">Import Calendar</a>
              <a class="btn btn-outline-warning btn-sm ms-2" href="/ui/shift-organizer">Shift Organizer</a>
              <a class="btn btn-outline-info btn-sm ms-2" href="/ui/availability">Availability</a>
            </div>
          </div>
        </nav>
        <main class="container py-4">
          $body
        </main>
        <script src="https://code.jquery.com/jquery-3.7.1.min.js" integrity="sha256-3gJwYpJPgH+U5Q5J5r3bJfFqvF8S2RkG8h6fWK3knlc=" crossorigin="anonymous"></script>
        <script src="https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.8/js/dataTables.bootstrap5.min.js"></script>
        <script src="https://cdn.datatables.net/colreorder/1.6.3/js/dataTables.colReorder.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" crossorigin="anonymous"></script>
        <script>
          (() => {
            const storageKey = 'scroll-pos:' + window.location.pathname;

            const saveScroll = () => {
              try {
                sessionStorage.setItem(storageKey, String(window.scrollY || window.pageYOffset || 0));
              } catch (error) {
                console.warn('Failed to save scroll position', error);
              }
            };

            const restoreScroll = () => {
              try {
                const saved = sessionStorage.getItem(storageKey);
                if (saved !== null) {
                  const y = Number.parseFloat(saved);
                  if (!Number.isNaN(y)) {
                    window.scrollTo({ top: y, behavior: 'auto' });
                  }
                }
              } catch (error) {
                console.warn('Failed to restore scroll position', error);
              }
            };

            document.addEventListener('DOMContentLoaded', () => {
              restoreScroll();
              document.querySelectorAll('form').forEach((form) => {
                form.addEventListener('submit', saveScroll);
              });
            });

            window.addEventListener('beforeunload', saveScroll);
          })();
        </script>
      </body>
    </html>
    """
    )

    return page.substitute(title=escape(title), body=body)


def _contact_label(name: str | None, phone: str | None) -> str:
    if name and phone:
        return f"{name} ({phone})"
    if name:
        return name
    if phone:
        return phone
    return "Unknown"


def _status_badge_class(status: str | None) -> str:
    """Map delivery status to Bootstrap badge color class."""
    if not status:
        return "secondary"
    status_lower = status.lower()
    if status_lower == "delivered":
        return "success"
    elif status_lower == "sent":
        return "info"
    elif status_lower == "queued":
        return "warning"
    elif status_lower in ("failed", "undelivered"):
        return "danger"
    elif status_lower == "read":
        return "primary"
    else:
        return "secondary"


@router.get("/ui/messages", response_class=HTMLResponse)
async def list_messages(hoh: HOHService = Depends(get_hoh_service)) -> HTMLResponse:
    messages = hoh.list_messages_with_events(org_id=1)
    grouped_events: list[dict] = []
    event_lookup: dict[str | int, dict] = {}

    for message in messages:
        event_id = message.get("event_id")
        event_key: str | int = event_id if event_id is not None else "unassigned"
        event_group = event_lookup.get(event_key)

        if not event_group:
            event_date = message.get("event_date")
            show_time_dt = message.get("show_time")
            # Convert UTC datetime to local time string for display
            show_time_str = utc_to_local_time_str(show_time_dt)
            event_group = {
                "event_id": event_id,
                "event_name": message.get("event_name") or "Unassigned",
                "event_date_display": event_date.strftime("%Y-%m-%d") if event_date else "",
                "show_time_display": show_time_str,
                "messages": [],
            }
            event_lookup[event_key] = event_group
            grouped_events.append(event_group)

        contact_label = _contact_label(
            name=message.get("contact_name"), phone=message.get("contact_phone")
        )
        direction = message.get("direction") or ""
        body = message.get("body") or ""
        delivery_status = message.get("delivery_status")

        timestamp = (
            message.get("sent_at")
            or message.get("received_at")
            or message.get("created_at")
        )
        timestamp_local = _to_israel_time(timestamp)
        timestamp_display = (
            timestamp_local.strftime("%Y-%m-%d %H:%M") if timestamp_local else ""
        )

        event_group["messages"].append(
            {
                "contact": contact_label,
                "direction": direction,
                "body": body,
                "timestamp_display": timestamp_display,
                "delivery_status": delivery_status,
            }
        )

    if not grouped_events:
        table = '<div class="alert alert-info">No messages yet.</div>'
    else:
        accordion_items = []
        for idx, event in enumerate(grouped_events):
            heading_id = f"heading{idx}"
            collapse_id = f"collapse{idx}"
            event_code = event.get("event_id")
            subtitle = " · ".join(
                filter(None, [event.get("event_date_display"), event.get("show_time_display")])
            )

            rows = []
            for message in event.get("messages", []):
                direction = message.get("direction") or ""
                delivery_status = message.get("delivery_status")
                status_class = _status_badge_class(delivery_status)
                # Use title case but preserve the actual status string for accuracy
                status_display = delivery_status.capitalize() if delivery_status and isinstance(delivery_status, str) else "N/A"
                
                rows.append(
                    """
                    <tr>
                      <td class=\"text-break\">{contact}</td>
                      <td><span class=\"badge text-bg-{direction_class}\">{direction}</span></td>
                      <td class=\"text-break\">{body}</td>
                      <td class=\"text-nowrap\">{timestamp}</td>
                      <td><span class=\"badge text-bg-{status_class}\">{status}</span></td>
                    </tr>
                    """.format(
                        contact=escape(message.get("contact") or ""),
                        direction_class="primary" if direction == "outgoing" else "secondary",
                        direction=escape(direction.title() if direction else ""),
                        body=escape(message.get("body") or ""),
                        timestamp=escape(message.get("timestamp_display") or ""),
                        status_class=status_class,
                        status=escape(status_display),
                    )
                )

            table_body = "".join(rows) or """
                <tr>
                  <td colspan=\"5\" class=\"text-center text-muted\">No messages for this event.</td>
                </tr>
            """

            accordion_items.append(
                """
                <div class=\"accordion-item\">
                  <h2 class=\"accordion-header\" id=\"{heading_id}\">
                    <button class=\"accordion-button{collapsed}\" type=\"button\" data-bs-toggle=\"collapse\" data-bs-target=\"#{collapse_id}\" aria-expanded=\"{expanded}\" aria-controls=\"{collapse_id}\">
                      <div>
                        <div class=\"fw-semibold\">{event_name} (קוד אירוע: {event_code})</div>
                        <div class=\"text-muted small\">{subtitle}</div>
                      </div>
                    </button>
                  </h2>
                  <div id=\"{collapse_id}\" class=\"accordion-collapse collapse{show}\" aria-labelledby=\"{heading_id}\" data-bs-parent=\"#messagesAccordion\">
                    <div class=\"accordion-body p-0\">
                      <div class=\"table-responsive mb-0\">\n                        <table class=\"table table-striped align-middle mb-0\">\n                          <thead class=\"table-light\">\n                            <tr>\n                              <th scope=\"col\">Contact</th>\n                              <th scope=\"col\">Direction</th>\n                              <th scope=\"col\">Body</th>\n                              <th scope=\"col\">Timestamp</th>\n                              <th scope=\"col\">Status</th>\n                            </tr>\n                          </thead>\n                          <tbody>\n                            {table_body}\n                          </tbody>\n                        </table>\n                      </div>
                    </div>
                  </div>
                </div>
                """.format(
                    heading_id=heading_id,
                    collapse_id=collapse_id,
                    collapsed=" collapsed",
                    expanded="false",
                    show="",
                    event_name=escape(event.get("event_name") or "Unassigned"),
                    event_code=escape(str(event_code) if event_code is not None else "N/A"),
                    subtitle=escape(subtitle or ""),
                    table_body=table_body,
                )
            )

        table = """
        <div class=\"accordion\" id=\"messagesAccordion\">
          {items}
        </div>
        """.format(items="".join(accordion_items))

    html = _render_page("Messages", table)
    return HTMLResponse(content=html)


def _contact_rows(contacts: list[dict]) -> str:
    if not contacts:
        return (
            '<tr><td colspan="4" class="text-center text-muted">No contacts yet.</td></tr>'
        )

    rows = []
    for contact in contacts:
        contact_id = contact.get("contact_id")
        usage_count = contact.get("event_usage_count") or 0
        is_locked = usage_count > 0
        delete_action = (
            """
                <button class=\"btn btn-sm btn-outline-danger\" type=\"button\" disabled>Delete</button>
                <div class=\"small text-muted mt-1\">לא ניתן למחוק - איש הקשר משויך לאירוע קיים. הסר אותו מהאירוע לפני מחיקה.</div>
            """
            if is_locked
            else """
                <form method=\"post\" action=\"/ui/contacts/{contact_id}/delete\" class=\"d-inline ms-1\" onsubmit=\"return confirm('האם אתה בטוח שברצונך למחוק את איש הקשר?');\">\n                  <button class=\"btn btn-sm btn-outline-danger\" type=\"submit\">Delete</button>\n                </form>
            """
            .format(contact_id=contact_id)
        )

        rows.append(
            """
            <tr>
              <td class=\"fw-semibold\">{name}</td>
              <td class=\"text-break\">{phone}</td>
              <td class=\"text-capitalize\">{role}</td>
              <td class=\"text-nowrap\">
                <a class=\"btn btn-sm btn-outline-secondary\" href=\"/ui/contacts/{contact_id}/edit\">Edit</a>
                {delete_action}
              </td>
            </tr>
            """.format(
                name=escape(contact.get("name") or ""),
                phone=escape(contact.get("phone") or ""),
                role=escape((contact.get("role") or "").capitalize()),
                contact_id=contact_id,
                delete_action=delete_action,
            )
        )

    return "".join(rows)


def _contacts_table(title: str, contacts: list[dict]) -> str:
    return """
    <div class="card shadow-sm">
      <div class="card-header bg-secondary text-white">{title}</div>
      <div class="card-body">
        <div class="table-responsive">
          <table class="table table-striped align-middle mb-0">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Phone</th>
                <th scope="col">Role</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """.format(title=escape(title), rows=_contact_rows(contacts))


@router.get("/ui/contacts", response_class=HTMLResponse)
async def list_contacts(hoh: HOHService = Depends(get_hoh_service)) -> HTMLResponse:
    grouped_contacts = hoh.list_contacts_by_role(org_id=1)

    add_form = """
    <div class=\"card mb-4 shadow-sm\">
      <div class=\"card-header bg-primary text-white\">Add Contact</div>
      <div class=\"card-body\">
        <form method=\"post\" action=\"/ui/contacts\">
          <div class=\"row\">
            <div class=\"col-md-5 mb-3\">
              <label class=\"form-label\" for=\"name\">Name</label>
              <input class=\"form-control\" id=\"name\" name=\"name\" type=\"text\" required>
            </div>
            <div class=\"col-md-4 mb-3\">
              <label class=\"form-label\" for=\"phone\">Phone</label>
              <input class=\"form-control\" id=\"phone\" name=\"phone\" type=\"text\" required>
            </div>
            <div class=\"col-md-3 mb-3\">
              <label class=\"form-label\" for=\"role\">Role</label>
              <select class=\"form-select\" id=\"role\" name=\"role\">
                <option value=\"producer\" selected>Producer</option>
                <option value=\"technical\">Technical</option>
              </select>
            </div>
          </div>
          <div class=\"d-flex justify-content-end\">
            <button class=\"btn btn-primary\" type=\"submit\">Add contact</button>
          </div>
        </form>
      </div>
    </div>
    """

    tables = """
    <div class=\"row g-4\">
      <div class=\"col-lg-6\">{producer_table}</div>
      <div class=\"col-lg-6\">{technical_table}</div>
    </div>
    """.format(
        producer_table=_contacts_table("Producer contacts", grouped_contacts.get("producer", [])),
        technical_table=_contacts_table(
            "Technical contacts", grouped_contacts.get("technical", [])
        ),
    )

    html = _render_page("Contacts", add_form + tables)
    return HTMLResponse(content=html)


@router.post("/ui/contacts")
async def add_contact(
    name: str = Form(...),
    phone: str = Form(...),
    role: str = Form("producer"),
    hoh: HOHService = Depends(get_hoh_service),
):
    hoh.create_contact(org_id=1, name=name.strip(), phone=phone.strip(), role=role.strip())
    return RedirectResponse(url="/ui/contacts", status_code=303)


@router.get("/ui/contacts/{contact_id}/edit", response_class=HTMLResponse)
async def edit_contact_form(
    contact_id: int, hoh: HOHService = Depends(get_hoh_service)
) -> HTMLResponse:
    contact = hoh.get_contact(org_id=1, contact_id=contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    name = escape(contact.get("name") or "")
    phone = escape(contact.get("phone") or "")
    role = (contact.get("role") or "producer").lower()

    form = f"""
    <div class=\"row justify-content-center\">\n
      <div class=\"col-lg-6\">
        <div class=\"card shadow-sm\">\n
          <div class=\"card-header bg-primary text-white\">Edit Contact</div>
          <div class=\"card-body\">
            <form method=\"post\" action=\"/ui/contacts/{contact_id}/edit\">\n
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"name\">Name</label>
                <input class=\"form-control\" id=\"name\" name=\"name\" type=\"text\" value=\"{name}\" required>
              </div>
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"phone\">Phone</label>
                <input class=\"form-control\" id=\"phone\" name=\"phone\" type=\"text\" value=\"{phone}\" required>
              </div>
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"role\">Role</label>
                <select class=\"form-select\" id=\"role\" name=\"role\">
                  <option value=\"producer\" {'selected' if role == 'producer' else ''}>Producer</option>
                  <option value=\"technical\" {'selected' if role == 'technical' else ''}>Technical</option>
                </select>
              </div>
              <div class=\"d-flex justify-content-end\">\n
                <a class=\"btn btn-outline-secondary me-2\" href=\"/ui/contacts\">Cancel</a>
                <button class=\"btn btn-primary\" type=\"submit\">Save changes</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
    """

    html = _render_page("Edit Contact", form)
    return HTMLResponse(content=html)


@router.post("/ui/contacts/{contact_id}/edit")
async def update_contact(
    contact_id: int,
    name: str = Form(...),
    phone: str = Form(...),
    role: str = Form("producer"),
    hoh: HOHService = Depends(get_hoh_service),
):
    hoh.update_contact(
        org_id=1,
        contact_id=contact_id,
        name=name.strip(),
        phone=phone.strip(),
        role=role.strip(),
    )
    return RedirectResponse(url="/ui/contacts", status_code=303)


@router.post("/ui/contacts/{contact_id}/delete")
async def delete_contact(contact_id: int, hoh: HOHService = Depends(get_hoh_service)):
    try:
        hoh.delete_contact(org_id=1, contact_id=contact_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/ui/contacts", status_code=303)


@router.get("/ui", response_class=HTMLResponse)
async def show_form() -> HTMLResponse:
    card = """
    <div class=\"row justify-content-center\">
      <div class=\"col-lg-6\">
        <div class=\"card shadow-sm\">
          <div class=\"card-header bg-primary text-white\">Add New Event</div>
          <div class=\"card-body\">
            <form method=\"post\" action=\"/ui/events\">
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"hall_id\">Hall ID</label>
                <input class=\"form-control\" id=\"hall_id\" name=\"hall_id\" type=\"number\" value=\"1\" required>
              </div>
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
                  <label class=\"form-label\" for=\"show_time\">Show time</label>
                  <input class=\"form-control\" id=\"show_time\" name=\"show_time\" type=\"time\" required>
                </div>
              </div>
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"producer_name\">Producer name</label>
                <input class=\"form-control\" id=\"producer_name\" name=\"producer_name\" type=\"text\" required>
              </div>
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"producer_phone\">Producer phone</label>
                <input class=\"form-control\" id=\"producer_phone\" name=\"producer_phone\" type=\"text\" required>
              </div>
              <div class=\"d-flex justify-content-end\">
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


@router.post("/ui/events")
async def add_event(
    hall_id: int = Form(...),
    event_name: str = Form(...),
    event_date: str = Form(...),
    show_time: str = Form(...),
    producer_name: str = Form(...),
    producer_phone: str = Form(...),
    hoh: HOHService = Depends(get_hoh_service),
):
    try:
        hoh.create_event_with_producer_conversation(
            org_id=1,
            hall_id=hall_id,
            event_name=event_name.strip(),
            event_date_str=event_date.strip(),
            show_time_str=show_time.strip(),
            producer_name=producer_name.strip(),
            producer_phone=producer_phone.strip(),
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to create event: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to add event") from exc

    return RedirectResponse(url="/ui/events", status_code=303)


@router.post("/ui/events/{event_id}/send-init")
async def ui_send_init(
    event_id: int,
    hoh: HOHService = Depends(get_hoh_service),
):
    try:
        await hoh.send_init_for_event(event_id=event_id, org_id=1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url="/ui/events", status_code=303)


@router.get("/ui/events", response_class=HTMLResponse)
async def list_events(hoh: HOHService = Depends(get_hoh_service)) -> HTMLResponse:
    events = hoh.list_events_for_org(org_id=1)
    # Get all active employees for dropdown
    active_employees = hoh.list_employees(org_id=1, active_only=True)

    table_rows = []
    for idx, row in enumerate(events):
        event_date = row.get("event_date")
        # Convert UTC datetimes to local Israel time strings
        show_time_dt = row.get("show_time")
        load_in_time_dt = row.get("load_in_time")
        created_at = _to_israel_time(row.get("created_at"))
        hall_label = row.get("hall_name") or (
            f"Hall #{row['hall_id']}" if row.get("hall_id") is not None else ""
        )
        date_display = event_date.strftime("%Y-%m-%d") if event_date else ""
        time_display = utc_to_local_time_str(show_time_dt)
        load_in_display = utc_to_local_time_str(load_in_time_dt)
        created_at_display = (
            created_at.strftime("%Y-%m-%d %H:%M") if created_at else ""
        )
        status = row.get("status") or ""
        delivery_status = row.get("latest_delivery_status")
        delivery_status_display = (
            delivery_status.capitalize()
            if delivery_status and isinstance(delivery_status, str)
            else "N/A"
        )
        delivery_status_class = _status_badge_class(delivery_status)
        producer_name = row.get("producer_name") or ""
        producer_phone = row.get("producer_phone") or ""
        producer_display = (
            f"{producer_name} ({producer_phone})"
            if producer_name and producer_phone
            else producer_name or producer_phone
        )
        technical_phone = row.get("technical_phone") or ""
        init_sent_at = _to_israel_time(row.get("init_sent_at"))
        init_sent_display = (
            init_sent_at.strftime("%Y-%m-%d %H:%M") if init_sent_at else ""
        )
        whatsapp_btn_class = (
            "btn btn-sm btn-primary" if init_sent_at else "btn btn-sm btn-success"
        )
        sent_indicator = (
            f"<div class=\\\"small text-success mt-1\\\">Sent {escape(init_sent_display)}</div>"
            if init_sent_display
            else "<div class=\\\"small text-muted mt-1\\\">Not sent yet</div>"
        )
        notes = row["notes"] or ""
        event_id = row.get("event_id")
        
        # Get shifts for this event
        shifts = hoh.list_event_employees(org_id=1, event_id=event_id)
        
        # Build shifts table for collapse
        shift_rows = []
        for shift in shifts:
            shift_id = shift.get("shift_id")
            emp_name = escape(shift.get("employee_name") or "")
            emp_phone = escape(shift.get("employee_phone") or "")
            shift_call_time = shift.get("call_time")
            shift_call_time_display = _to_israel_time(shift_call_time).strftime("%Y-%m-%d %H:%M") if shift_call_time else ""
            # For edit form, we need datetime-local format (YYYY-MM-DDTHH:MM)
            shift_call_time_edit = _to_israel_time(shift_call_time).strftime("%Y-%m-%dT%H:%M") if shift_call_time else ""
            shift_role_val = escape(shift.get("shift_role") or "")
            shift_notes_val = escape(shift.get("notes") or "")
            reminder_sent = shift.get("reminder_24h_sent_at")
            reminder_badge = (
                '<span class="badge bg-success">Sent</span>' if reminder_sent 
                else '<span class="badge bg-secondary">Failed</span>'
            )
            
            shift_rows.append(f"""
                <tr>
                  <td>{emp_name}</td>
                  <td>{emp_phone}</td>
                  <td>{shift_call_time_display}</td>
                  <td>{shift_role_val}</td>
                  <td class="text-break">{shift_notes_val}</td>
                  <td>{reminder_badge}</td>
                  <td class="text-nowrap">
                    <button class="btn btn-sm btn-outline-secondary" 
                            onclick="showEditShiftModal({event_id}, {shift_id}, '{shift_call_time_edit}', '{shift_role_val}', '{shift_notes_val}')">
                      Edit
                    </button>
                    <form method="post" action="/ui/events/{event_id}/shifts/{shift_id}/delete" class="d-inline ms-1"
                          onsubmit="return confirm('מחק משמרת זו?');">
                      <button class="btn btn-sm btn-outline-danger" type="submit">Delete</button>
                    </form>
                    <form method="post" action="/ui/events/{event_id}/shifts/{shift_id}/send-reminder" class="d-inline ms-1">
                      <button class="btn btn-sm btn-outline-info" type="submit">Send Reminder</button>
                    </form>
                  </td>
                </tr>
            """)
        
        shift_table_body = "".join(shift_rows) or """
            <tr>
              <td colspan="7" class="text-center text-muted">אין משמרות / No shifts assigned yet.</td>
            </tr>
        """
        
        # Build employee dropdown options
        employee_options = []
        for emp in active_employees:
            emp_id = emp.get("employee_id")
            emp_name = escape(emp.get("name") or "")
            employee_options.append(f'<option value="{emp_id}">{emp_name}</option>')
        employee_dropdown = "".join(employee_options)
        
        # Build the collapse ID
        collapse_id = f"collapseShifts{event_id}"
        
        # Build the shift collapse HTML
        shifts_collapse = f"""
        <tr class="collapse-row" id="{collapse_id}" style="display:none;">
          <td colspan="12" class="p-0">
            <div class="card m-2">
              <div class="card-header bg-light">
                <strong>Employees Shifts</strong>
              </div>
              <div class="card-body">
                <div class="table-responsive">
                  <table class="table table-sm table-hover mb-3">
                    <thead>
                      <tr>
                        <th>Employee</th>
                        <th>Phone</th>
                        <th>Shift Time</th>
                        <th>תפקיד / Role</th>
                        <th>Notes</th>
                        <th>תזכורת / Reminder</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shift_table_body}
                    </tbody>
                  </table>
                </div>
                <hr>
                <div class="card bg-light">
                  <div class="card-body">
                    <h6>Add Employee to Shift</h6>
                    <form method="post" action="/ui/events/{event_id}/shifts">
                      <div class="row">
                        <div class="col-md-3 mb-2">
                          <label class="form-label" for="employee_id_{event_id}">Employee</label>
                          <select class="form-select form-select-sm" id="employee_id_{event_id}" name="employee_id" required>
                            <option value="">בחר עובד...</option>
                            {employee_dropdown}
                          </select>
                        </div>
                        <div class="col-md-3 mb-2">
                          <label class="form-label" for="call_time_{event_id}">Shift Time</label>
                          <input class="form-control form-control-sm" id="call_time_{event_id}" name="call_time" type="datetime-local" required>
                        </div>
                        <div class="col-md-2 mb-2">
                          <label class="form-label" for="shift_role_{event_id}">תפקיד / Role</label>
                          <input class="form-control form-control-sm" id="shift_role_{event_id}" name="shift_role" type="text">
                        </div>
                        <div class="col-md-3 mb-2">
                          <label class="form-label" for="notes_{event_id}">Notes</label>
                          <input class="form-control form-control-sm" id="notes_{event_id}" name="notes" type="text">
                        </div>
                        <div class="col-md-1 mb-2 d-flex align-items-end">
                          <button class="btn btn-sm btn-primary w-100" type="submit">Add</button>
                        </div>
                      </div>
                    </form>
                  </div>
                </div>
              </div>
            </div>
          </td>
        </tr>
        """

        table_rows.append(
            """
            <tr class="event-row">
              <td>
                <button class="btn btn-sm btn-outline-primary" type="button" onclick="toggleCollapse('{collapse_id}')">
                  <span id="icon-{collapse_id}">▶</span> טכנאים
                </button>
              </td>
              <td>{name}</td>
              <td>{date}</td>
              <td>{time}</td>
              <td>{load_in}</td>
              <td>{hall}</td>
              <td>{status}</td>
              <td><span class=\"badge text-bg-{delivery_status_class}\">{delivery_status}</span></td>
              <td class=\"text-break\">{notes}</td>
              <td>{producer_phone}</td>
              <td>{technical_phone}</td>
              <td class=\"text-nowrap\">
                <form method=\"post\" action=\"/ui/events/{event_id}/send-init\" class=\"d-inline\">
                  <button class=\"{whatsapp_btn_class}\" type=\"submit\">Send WhatsApp</button>
                </form>
                {sent_indicator}
                <a class=\"btn btn-sm btn-outline-secondary ms-1\" href=\"/ui/events/{event_id}/edit\">Edit</a>
                <form method=\"post\" action=\"/ui/events/{event_id}/delete\" class=\"d-inline ms-1\" onsubmit=\"return confirm('האם אתה בטוח למחוק את האירוע?');\">
                  <button class=\"btn btn-sm btn-outline-danger\" type=\"submit\">Delete</button>
                </form>
              </td>
            </tr>
            {shifts_collapse}
            """.format(
                collapse_id=collapse_id,
                name=escape(row.get("name") or ""),
                date=escape(date_display),
                time=escape(time_display),
                load_in=escape(load_in_display),
                hall=escape(hall_label or ""),
                status=escape(status),
                delivery_status=escape(delivery_status_display),
                delivery_status_class=delivery_status_class,
                notes=escape(notes),
                producer_phone=escape(producer_display),
                technical_phone=escape(technical_phone),
                event_id=event_id,
                whatsapp_btn_class=whatsapp_btn_class,
                sent_indicator=sent_indicator,
                shift_table_body=shift_table_body,
                employee_dropdown=employee_dropdown,
                shifts_collapse=shifts_collapse,
            )
        )

    table_body = "".join(table_rows) or """
        <tr>
          <td colspan=\"12\" class=\"text-center text-muted\">No events yet.</td>
        </tr>
    """

    table_template = """
    <!-- Edit Shift Modal -->
    <div class="modal fade" id="editShiftModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">ערוך משמרת / Edit Shift</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <form id="editShiftForm" method="post">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Shift Time</label>
                <input class="form-control" id="edit_call_time" name="call_time" type="datetime-local" required>
              </div>
              <div class="mb-3">
                <label class="form-label">תפקיד / Role</label>
                <input class="form-control" id="edit_shift_role" name="shift_role" type="text">
              </div>
              <div class="mb-3">
                <label class="form-label">Notes</label>
                <textarea class="form-control" id="edit_notes" name="notes" rows="3"></textarea>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">ביטול / Cancel</button>
              <button type="submit" class="btn btn-primary">שמור / Save</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    
    <div class=\"card\">
      <div class=\"card-header bg-secondary text-white\">Events</div>
      <div class=\"card-body\">
        <div class=\"table-responsive\">
          <table id=\"events-table\" class=\"table table-striped align-middle\">
            <thead>
              <tr>
                <th scope=\"col\">Shifts</th>
                <th scope=\"col\">Name</th>
                <th scope=\"col\">Date</th>
                <th scope=\"col\">Show Time</th>
                <th scope=\"col\">Load In</th>
                <th scope=\"col\">Hall</th>
                <th scope=\"col\">Event Status</th>
                <th scope=\"col\">Status</th>
                <th scope=\"col\">Notes</th>
                <th scope=\"col\">Producer Phone</th>
                <th scope=\"col\">Technical Phone</th>
                <th scope=\"col\">Actions</th>
              </tr>
            </thead>
            <tbody>
              __TABLE_BODY__
            </tbody>
          </table>
        </div>
      </div>
    </div>
    <script>
      function toggleCollapse(collapseId) {
        const row = document.getElementById(collapseId);
        const icon = document.getElementById('icon-' + collapseId);
        if (row.style.display === 'none') {
          row.style.display = '';
          icon.textContent = '▼';
        } else {
          row.style.display = 'none';
          icon.textContent = '▶';
        }
      }
      
      function showEditShiftModal(eventId, shiftId, callTime, role, notes) {
        // Unescape HTML entities
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = role;
        const unescapedRole = tempDiv.textContent;
        tempDiv.innerHTML = notes;
        const unescapedNotes = tempDiv.textContent;
        
        document.getElementById('edit_call_time').value = callTime;
        document.getElementById('edit_shift_role').value = unescapedRole;
        document.getElementById('edit_notes').value = unescapedNotes;
        document.getElementById('editShiftForm').action = '/ui/events/' + eventId + '/shifts/' + shiftId + '/edit';
        
        const modal = new bootstrap.Modal(document.getElementById('editShiftModal'));
        modal.show();
      }
    </script>
    <script>
      document.addEventListener("DOMContentLoaded", function () {
        const tableElement = document.getElementById("events-table");
        const hasJQuery = typeof window.jQuery !== "undefined";
        const hasDataTables =
          hasJQuery && typeof window.jQuery.fn.DataTable === "function";

        if (!tableElement || !hasDataTables) {
          console.warn("Events table could not initialize DataTables.");
          return;
        }

        const $table = window.jQuery(tableElement);
        const currentHeaders = Array.from(
          tableElement.querySelectorAll("thead th")
        ).map((th) => th.textContent.trim());
        const stateKey = `DataTables_${tableElement.id}_${window.location.pathname}`;

        $table.DataTable({
          stateSave: true,
          stateDuration: -1,
          colReorder: true,
          order: [],
          stateSaveParams: function (_settings, data) {
            data.columnHeaders = currentHeaders;
          },
          stateSaveCallback: function (_settings, data) {
            try {
              localStorage.setItem(stateKey, JSON.stringify(data));
            } catch (error) {
              console.warn("Failed to save table state", error);
            }
          },
          stateLoadCallback: function (_settings) {
            const savedState = localStorage.getItem(stateKey);
            if (!savedState) {
              return null;
            }

            try {
              const parsedState = JSON.parse(savedState);
              if (
                Array.isArray(parsedState.columnHeaders) &&
                parsedState.columnHeaders.join("|||") !==
                  currentHeaders.join("|||")
              ) {
                localStorage.removeItem(stateKey);
                return null;
              }

              return parsedState;
            } catch (error) {
              console.warn("Failed to load saved table state", error);
              return null;
            }
          },
        });
      });
    </script>
    """

    table = table_template.replace("__TABLE_BODY__", table_body)

    html = _render_page("Events", table)
    return HTMLResponse(content=html)


@router.get("/ui/events/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(
    event_id: int, hoh: HOHService = Depends(get_hoh_service)
) -> HTMLResponse:
    event = hoh.get_event_with_contacts(org_id=1, event_id=event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event_date = event.get("event_date")
    show_time_dt = event.get("show_time")
    load_in_time_dt = event.get("load_in_time")

    event_date_str = event_date.strftime("%Y-%m-%d") if event_date else ""
    # Convert UTC datetimes to local Israel time strings for display
    # This prevents the "2 hour shift" bug on edit
    show_time_str = utc_to_local_time_str(show_time_dt)
    load_in_time_str = utc_to_local_time_str(load_in_time_dt)

    producer_name = event.get("producer_name") or ""
    producer_phone = event.get("producer_phone") or ""
    technical_name = event.get("technical_name") or ""
    technical_phone = event.get("technical_phone") or ""
    notes = event.get("notes") or ""

    form = f"""
    <div class=\"row justify-content-center\">
      <div class=\"col-lg-8\">
        <div class=\"card shadow-sm\">
          <div class=\"card-header bg-primary text-white\">Edit Event</div>
          <div class=\"card-body\">
            <form method=\"post\" action=\"/ui/events/{event_id}/edit\">
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"event_name\">Event name</label>
                <input class=\"form-control\" id=\"event_name\" name=\"event_name\" type=\"text\" value=\"{escape(event.get('name') or '')}\" required>
              </div>
              <div class=\"row\">
                <div class=\"col-md-4 mb-3\">
                  <label class=\"form-label\" for=\"event_date\">Event date</label>
                  <input class=\"form-control\" id=\"event_date\" name=\"event_date\" type=\"date\" value=\"{escape(event_date_str)}\" required>
                </div>
                <div class=\"col-md-4 mb-3\">
                  <label class=\"form-label\" for=\"show_time\">Show time</label>
                  <input class=\"form-control\" id=\"show_time\" name=\"show_time\" type=\"time\" value=\"{escape(show_time_str)}\">
                </div>
                <div class=\"col-md-4 mb-3\">
                  <label class=\"form-label\" for=\"load_in_time\">Load-in time</label>
                  <input class=\"form-control\" id=\"load_in_time\" name=\"load_in_time\" type=\"time\" value=\"{escape(load_in_time_str)}\">
                </div>
              </div>
              <div class=\"row\">
                <div class=\"col-md-6 mb-3\">
                  <label class=\"form-label\" for=\"producer_name\">Producer contact name</label>
                  <input class=\"form-control\" id=\"producer_name\" name=\"producer_name\" type=\"text\" value=\"{escape(producer_name)}\">
                </div>
                <div class=\"col-md-6 mb-3\">
                  <label class=\"form-label\" for=\"producer_phone\">Producer phone</label>
                  <input class=\"form-control\" id=\"producer_phone\" name=\"producer_phone\" type=\"text\" value=\"{escape(producer_phone)}\">
                </div>
              </div>
              <div class=\"row\">
                <div class=\"col-md-6 mb-3\">
                  <label class=\"form-label\" for=\"technical_name\">Technical contact name</label>
                  <input class=\"form-control\" id=\"technical_name\" name=\"technical_name\" type=\"text\" value=\"{escape(technical_name)}\">
                </div>
                <div class=\"col-md-6 mb-3\">
                  <label class=\"form-label\" for=\"technical_phone\">Technical phone</label>
                  <input class=\"form-control\" id=\"technical_phone\" name=\"technical_phone\" type=\"text\" value=\"{escape(technical_phone)}\">
                </div>
              </div>
              <div class=\"mb-3\">
                <label class=\"form-label\" for=\"notes\">Notes</label>
                <textarea class=\"form-control\" id=\"notes\" name=\"notes\" rows=\"3\">{escape(notes)}</textarea>
              </div>
              <div class=\"d-flex justify-content-end\">
                <a class=\"btn btn-outline-secondary me-2\" href=\"/ui/events\">Cancel</a>
                <button class=\"btn btn-primary\" type=\"submit\">Save changes</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
    """

    html = _render_page("Edit Event", form)
    return HTMLResponse(content=html)


@router.post("/ui/events/{event_id}/edit")
async def update_event(
    event_id: int,
    event_name: str = Form(...),
    event_date: str = Form(...),
    show_time: str | None = Form(None),
    load_in_time: str | None = Form(None),
    producer_name: str | None = Form(None),
    producer_phone: str | None = Form(None),
    technical_name: str | None = Form(None),
    technical_phone: str | None = Form(None),
    notes: str | None = Form(None),
    hoh: HOHService = Depends(get_hoh_service),
):
    try:
        hoh.update_event_with_contacts(
            org_id=1,
            event_id=event_id,
            event_name=event_name.strip(),
            event_date_str=event_date.strip(),
            show_time_str=show_time.strip() if show_time else None,
            load_in_time_str=load_in_time.strip() if load_in_time else None,
            producer_name=producer_name.strip() if producer_name else None,
            producer_phone=producer_phone.strip() if producer_phone else None,
            technical_name=technical_name.strip() if technical_name else None,
            technical_phone=technical_phone.strip() if technical_phone else None,
            notes=notes.strip() if notes else None,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to update event: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update event") from exc

    return RedirectResponse(url="/ui/events", status_code=303)


@router.post("/ui/events/{event_id}/delete")
async def delete_event(event_id: int, hoh: HOHService = Depends(get_hoh_service)):
    try:
        hoh.delete_event(org_id=1, event_id=event_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to delete event: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete event") from exc

    return RedirectResponse(url="/ui/events", status_code=303)


# ==========================================
# SHIFT MANAGEMENT (Employee Shifts for Events)
# ==========================================

@router.post("/ui/events/{event_id}/shifts")
async def create_shift(
    event_id: int,
    employee_id: int = Form(...),
    call_time: str = Form(...),
    shift_role: str | None = Form(None),
    notes: str | None = Form(None),
    hoh: HOHService = Depends(get_hoh_service),
):
    """Assign an employee to an event shift."""
    try:
        # Parse call_time from datetime-local format (e.g., "2024-07-15T21:00")
        # Treats input as Israel local time and makes it timezone-aware
        call_time_tz = parse_datetime_local_input(call_time)
        
        hoh.assign_employee_to_event(
            org_id=1,
            event_id=event_id,
            employee_id=employee_id,
            call_time=call_time_tz,
            shift_role=shift_role.strip() if shift_role else None,
            notes=notes.strip() if notes else None,
        )
    except Exception as exc:
        # Check if it's a UNIQUE constraint violation (duplicate employee assignment)
        error_str = str(exc).lower()
        if "unique" in error_str or "duplicate" in error_str:
            raise HTTPException(
                status_code=400,
                detail="עובד זה כבר משויך לאירוע / Employee is already assigned to this event"
            ) from exc
        logger.exception("Failed to create shift: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to create shift: {exc}") from exc
    
    return RedirectResponse(url="/ui/events", status_code=303)


@router.post("/ui/events/{event_id}/shifts/{shift_id}/edit")
async def update_shift(
    event_id: int,
    shift_id: int,
    call_time: str = Form(...),
    shift_role: str | None = Form(None),
    notes: str | None = Form(None),
    hoh: HOHService = Depends(get_hoh_service),
):
    """Update a shift."""
    try:
        # Parse call_time from datetime-local format (e.g., "2024-07-15T21:00")
        # Treats input as Israel local time and makes it timezone-aware
        call_time_tz = parse_datetime_local_input(call_time)
        
        hoh.update_shift(
            org_id=1,
            shift_id=shift_id,
            call_time=call_time_tz,
            shift_role=shift_role.strip() if shift_role else None,
            notes=notes.strip() if notes else None,
        )
    except Exception as exc:
        logger.exception("Failed to update shift: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to update shift: {exc}") from exc
    
    return RedirectResponse(url="/ui/events", status_code=303)


@router.post("/ui/events/{event_id}/shifts/{shift_id}/delete")
async def delete_shift(
    event_id: int,
    shift_id: int,
    hoh: HOHService = Depends(get_hoh_service)
):
    """Delete a shift."""
    try:
        hoh.delete_shift(org_id=1, shift_id=shift_id)
    except Exception as exc:
        logger.exception("Failed to delete shift: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to delete shift: {exc}") from exc
    
    return RedirectResponse(url="/ui/events", status_code=303)


@router.post("/ui/events/{event_id}/shifts/{shift_id}/send-reminder")
async def send_shift_reminder(
    event_id: int,
    shift_id: int,
    hoh: HOHService = Depends(get_hoh_service)
):
    """Send a reminder to the employee for this shift."""
    try:
        shift = hoh.get_shift(org_id=1, shift_id=shift_id)
        if not shift or shift.get("event_id") != event_id:
            raise HTTPException(status_code=404, detail="Shift not found")

        hoh.send_shift_reminder(org_id=1, shift_id=shift_id)

        logger.info(f"Reminder sent successfully for shift {shift_id}")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to send reminder: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to send reminder: {exc}") from exc
    
    return RedirectResponse(url="/ui/events", status_code=303)


@router.get("/ui/calendar-import", response_class=HTMLResponse)
async def calendar_import_page() -> HTMLResponse:
    """Calendar import page with staging events management."""
    page_html = """
    <div class="row">
      <div class="col-12">
        <div class="card shadow-sm mb-4">
          <div class="card-header bg-success text-white">
            <h5 class="mb-0">Import Monthly Calendar (Excel)</h5>
          </div>
          <div class="card-body">
            <div class="alert alert-info">
              <strong>Instructions:</strong>
              <ul class="mb-0">
                <li>Upload an Excel (.xlsx) file with venue calendar data</li>
                <li>Review and edit staging events in the table below</li>
                <li>Valid events (green) can be committed to the official events table</li>
                <li>Invalid events (red) must be fixed before commit</li>
                <li>Warnings (orange) don't block commit but should be reviewed</li>
              </ul>
            </div>
            
            <form id="uploadForm" enctype="multipart/form-data">
              <div class="row align-items-end">
                <div class="col-md-8 mb-3">
                  <label for="excelFile" class="form-label">Select Excel File (.xlsx)</label>
                  <input type="file" class="form-control" id="excelFile" name="file" accept=".xlsx" required>
                </div>
                <div class="col-md-4 mb-3">
                  <button type="submit" class="btn btn-primary w-100">
                    <span class="spinner-border spinner-border-sm d-none" id="uploadSpinner"></span>
                    Upload & Parse
                  </button>
                </div>
              </div>
            </form>
            
            <div id="uploadStatus" class="mt-3"></div>
          </div>
        </div>

        <div class="card shadow-sm">
          <div class="card-header bg-secondary text-white d-flex justify-content-between align-items-center">
            <h5 class="mb-0">Staging Events</h5>
            <div>
              <button class="btn btn-sm btn-outline-light" onclick="revalidateAll()">
                <span class="spinner-border spinner-border-sm d-none" id="validateSpinner"></span>
                Revalidate All
              </button>
              <button class="btn btn-sm btn-success ms-2" onclick="showCommitModal()">
                Commit to Events
              </button>
              <button class="btn btn-sm btn-warning ms-2" onclick="addNewRow()">
                Add Row
              </button>
              <button class="btn btn-sm btn-danger ms-2" onclick="clearAll()">
                Clear All
              </button>
            </div>
          </div>
          <div class="card-body">
            <div id="stagingSummary" class="alert alert-secondary">
              Loading staging events...
            </div>
            
            <div class="table-responsive">
              <table class="table table-sm table-hover" id="stagingTable">
                <thead class="table-light">
                  <tr>
                    <th>Row</th>
                    <th>Date</th>
                    <th>Show Time</th>
                    <th>Event Name</th>
                    <th>Load In</th>
                    <th>Series</th>
                    <th>Producer</th>
                    <th>Phone</th>
                    <th>Notes</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody id="stagingTableBody">
                  <tr>
                    <td colspan="11" class="text-center text-muted">No staging events. Upload an Excel file to begin.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Commit Modal -->
    <div class="modal fade" id="commitModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Commit to Official Events</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div id="commitModalContent">
              <p><strong>Ready to commit:</strong> <span id="commitValidCount">0</span> valid events</p>
              <div id="commitDuplicateWarning" class="alert alert-warning d-none">
                <strong>Warning:</strong> <span id="commitDuplicateCount">0</span> potential duplicate(s) detected.
                <div class="form-check mt-2">
                  <input class="form-check-input" type="checkbox" id="skipDuplicatesCheck">
                  <label class="form-check-label" for="skipDuplicatesCheck">
                    Skip duplicates during commit
                  </label>
                </div>
              </div>
              <p class="text-muted">This will create events and contacts in the official tables. Are you sure?</p>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-success" onclick="commitEvents()">
              <span class="spinner-border spinner-border-sm d-none" id="commitSpinner"></span>
              Commit
            </button>
          </div>
        </div>
      </div>
    </div>

    <script>
    let currentStagingData = [];
    let duplicateWarnings = [];

    // Load staging events on page load
    document.addEventListener('DOMContentLoaded', function() {
      loadStagingEvents();
    });

    // Upload form handler
    document.getElementById('uploadForm').addEventListener('submit', async function(e) {
      e.preventDefault();
      
      const spinner = document.getElementById('uploadSpinner');
      const fileInput = document.getElementById('excelFile');
      const statusDiv = document.getElementById('uploadStatus');
      
      if (!fileInput.files[0]) {
        statusDiv.innerHTML = '<div class="alert alert-danger">Please select a file</div>';
        return;
      }
      
      spinner.classList.remove('d-none');
      statusDiv.innerHTML = '';
      
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      formData.append('org_id', '1');
      
      try {
        const response = await fetch('/import/upload', {
          method: 'POST',
          body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
          statusDiv.innerHTML = `
            <div class="alert alert-success">
              <strong>Upload successful!</strong><br>
              Total rows: ${result.total_rows}<br>
              Valid: ${result.valid_rows}<br>
              Invalid: ${result.invalid_rows}<br>
              Duplicates: ${result.duplicate_warnings.length}
            </div>
          `;
          duplicateWarnings = result.duplicate_warnings;
          loadStagingEvents();
          fileInput.value = '';
        } else {
          statusDiv.innerHTML = `<div class="alert alert-danger">Error: ${result.detail}</div>`;
        }
      } catch (error) {
        statusDiv.innerHTML = `<div class="alert alert-danger">Upload failed: ${error.message}</div>`;
      } finally {
        spinner.classList.add('d-none');
      }
    });

    async function loadStagingEvents() {
      try {
        const response = await fetch('/import/staging?org_id=1');
        const events = await response.json();
        
        currentStagingData = events;
        renderStagingTable(events);
        updateSummary(events);
      } catch (error) {
        console.error('Failed to load staging events:', error);
      }
    }

    function renderStagingTable(events) {
      const tbody = document.getElementById('stagingTableBody');
      
      if (events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted">No staging events. Upload an Excel file to begin.</td></tr>';
        return;
      }
      
      tbody.innerHTML = events.map(event => {
        const rowClass = event.is_valid ? 'table-success' :
                        (event.warnings.length > 0 ? 'table-warning' : 'table-danger');
        const statusBadge = event.is_valid ?
          '<span class="badge bg-success">Valid</span>' :
          '<span class="badge bg-danger">Invalid</span>';

        const errorsHtml = event.errors.length > 0 ?
          '<div class="small text-danger">' + event.errors.join('; ') + '</div>' : '';
        const warningsHtml = event.warnings.length > 0 ?
          '<div class="small text-warning">' + event.warnings.join('; ') + '</div>' : '';

        const dateValue = event.date || '';
        const showTimeValue = toTimeValue(event.show_time);
        const loadInValue = toTimeValue(event.load_in);

        return `
          <tr class="${rowClass}">
            <td>${event.row_index}</td>
            <td><input type="date" class="form-control form-control-sm" value="${escapeAttr(dateValue)}" onchange="updateField(${event.id}, 'date', this.value)"></td>
            <td><input type="time" class="form-control form-control-sm" value="${escapeAttr(showTimeValue)}" onchange="updateField(${event.id}, 'show_time', this.value)"></td>
            <td><input type="text" class="form-control form-control-sm" value="${escapeAttr(event.name || '')}" placeholder="Event name" onchange="updateField(${event.id}, 'name', this.value)"></td>
            <td><input type="time" class="form-control form-control-sm" value="${escapeAttr(loadInValue)}" onchange="updateField(${event.id}, 'load_in', this.value)"></td>
            <td><input type="text" class="form-control form-control-sm" value="${escapeAttr(event.event_series || '')}" placeholder="Series" onchange="updateField(${event.id}, 'event_series', this.value)"></td>
            <td><input type="text" class="form-control form-control-sm" value="${escapeAttr(event.producer_name || '')}" placeholder="Producer" onchange="updateField(${event.id}, 'producer_name', this.value)"></td>
            <td><input type="text" class="form-control form-control-sm" value="${escapeAttr(event.producer_phone || '')}" placeholder="Phone" onchange="updateField(${event.id}, 'producer_phone', this.value)"></td>
            <td><input type="text" class="form-control form-control-sm" value="${escapeAttr(event.notes || '')}" placeholder="Notes" onchange="updateField(${event.id}, 'notes', this.value)"></td>
            <td>${statusBadge}${errorsHtml}${warningsHtml}</td>
            <td>
              <button class="btn btn-sm btn-outline-danger" onclick="deleteRow(${event.id})">Delete</button>
            </td>
          </tr>
        `;
      }).join('');
    }

    function escape(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    function escapeAttr(str) {
      if (str === undefined || str === null) return '';
      return String(str).replace(/"/g, '&quot;');
    }

    function toTimeValue(timeValue) {
      if (!timeValue) return '';
      return String(timeValue).substring(0, 5);
    }

    function updateSummary(events) {
      const validCount = events.filter(e => e.is_valid).length;
      const invalidCount = events.length - validCount;
      
      document.getElementById('stagingSummary').innerHTML = `
        <strong>Summary:</strong> 
        ${events.length} total events | 
        ${validCount} valid | 
        ${invalidCount} invalid
        ${duplicateWarnings.length > 0 ? ` | ${duplicateWarnings.length} potential duplicates` : ''}
      `;
    }

    async function deleteRow(stagingId) {
      if (!confirm('Delete this staging event?')) return;
      
      try {
        const response = await fetch(`/import/staging/${stagingId}?org_id=1`, {
          method: 'DELETE'
        });
        
        if (response.ok) {
          loadStagingEvents();
        } else {
          alert('Failed to delete event');
        }
      } catch (error) {
        alert('Failed to delete event: ' + error.message);
      }
    }

    async function updateField(stagingId, field, rawValue) {
      const payload = {{}};
      const value = rawValue === '' ? null : rawValue;
      payload[field] = value;

      try {
        const response = await fetch(`/import/staging/${stagingId}?org_id=1`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (response.ok) {
          currentStagingData = currentStagingData.map(event => event.id === stagingId ? result : event);
          renderStagingTable(currentStagingData);
          updateSummary(currentStagingData);
        } else {
          alert('Update failed: ' + (result.detail || 'Unknown error'));
        }
      } catch (error) {
        alert('Update failed: ' + error.message);
      }
    }

    async function addNewRow() {
      try {
        const response = await fetch('/import/staging?org_id=1', {
          method: 'POST'
        });
        
        if (response.ok) {
          loadStagingEvents();
        } else {
          alert('Failed to add row');
        }
      } catch (error) {
        alert('Failed to add row: ' + error.message);
      }
    }

    async function revalidateAll() {
      const spinner = document.getElementById('validateSpinner');
      spinner.classList.remove('d-none');
      
      try {
        const response = await fetch('/import/validate?org_id=1', {
          method: 'POST'
        });
        
        const result = await response.json();
        duplicateWarnings = result.duplicate_warnings;
        
        if (response.ok) {
          loadStagingEvents();
        } else {
          alert('Validation failed');
        }
      } catch (error) {
        alert('Validation failed: ' + error.message);
      } finally {
        spinner.classList.add('d-none');
      }
    }

    async function clearAll() {
      if (!confirm('Clear all staging events? This cannot be undone.')) return;
      
      try {
        const response = await fetch('/import/clear?org_id=1', {
          method: 'POST'
        });
        
        if (response.ok) {
          duplicateWarnings = [];
          loadStagingEvents();
        } else {
          alert('Failed to clear');
        }
      } catch (error) {
        alert('Failed to clear: ' + error.message);
      }
    }

    function showCommitModal() {
      const validCount = currentStagingData.filter(e => e.is_valid).length;
      
      if (validCount === 0) {
        alert('No valid events to commit. Please fix errors first.');
        return;
      }
      
      document.getElementById('commitValidCount').textContent = validCount;
      
      if (duplicateWarnings.length > 0) {
        document.getElementById('commitDuplicateCount').textContent = duplicateWarnings.length;
        document.getElementById('commitDuplicateWarning').classList.remove('d-none');
      } else {
        document.getElementById('commitDuplicateWarning').classList.add('d-none');
      }
      
      const modal = new bootstrap.Modal(document.getElementById('commitModal'));
      modal.show();
    }

    async function commitEvents() {
      const spinner = document.getElementById('commitSpinner');
      const skipDuplicates = document.getElementById('skipDuplicatesCheck').checked;
      
      spinner.classList.remove('d-none');
      
      try {
        const formData = new FormData();
        formData.append('skip_duplicates', skipDuplicates);
        formData.append('org_id', '1');
        
        const response = await fetch('/import/commit', {
          method: 'POST',
          body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
          bootstrap.Modal.getInstance(document.getElementById('commitModal')).hide();
          alert(`Success! Committed ${result.committed_count} events.${result.skipped_duplicates > 0 ? ` Skipped ${result.skipped_duplicates} duplicates.` : ''}`);
          duplicateWarnings = [];
          loadStagingEvents();
        } else {
          alert('Commit failed: ' + result.detail);
        }
      } catch (error) {
        alert('Commit failed: ' + error.message);
      } finally {
        spinner.classList.add('d-none');
      }
    }
    </script>
    """
    
    html = _render_page("Import Calendar", page_html)
    return HTMLResponse(content=html)


# ==========================================
# EMPLOYEE MANAGEMENT
# ==========================================

@router.get("/ui/employees", response_class=HTMLResponse)
async def list_employees(
    show_inactive: bool = False,
    hoh: HOHService = Depends(get_hoh_service)
) -> HTMLResponse:
    """Employee management page - list all employees with CRUD operations."""
    employees = hoh.list_employees(org_id=1, active_only=not show_inactive)
    
    # Build add form
    add_form = """
    <div class="card mb-4 shadow-sm">
      <div class="card-header bg-primary text-white">הוסף עובד חדש / Add Employee</div>
      <div class="card-body">
        <form method="post" action="/ui/employees">
          <div class="row">
            <div class="col-md-3 mb-3">
              <label class="form-label" for="name">שם / Name</label>
              <input class="form-control" id="name" name="name" type="text" required>
            </div>
            <div class="col-md-3 mb-3">
              <label class="form-label" for="phone">Phone</label>
              <input class="form-control" id="phone" name="phone" type="text" required>
            </div>
            <div class="col-md-3 mb-3">
              <label class="form-label" for="role">תפקיד / Role</label>
              <input class="form-control" id="role" name="role" type="text">
            </div>
            <div class="col-md-3 mb-3">
              <label class="form-label" for="notes">Notes</label>
              <input class="form-control" id="notes" name="notes" type="text">
            </div>
          </div>
          <div class="d-flex justify-content-end">
            <button class="btn btn-primary" type="submit">הוסף / Add Employee</button>
          </div>
        </form>
      </div>
    </div>
    """
    
    # Build filter toggle
    filter_toggle = f"""
    <div class="mb-3">
      <a class="btn btn-sm btn-outline-secondary" href="/ui/employees?show_inactive={'false' if show_inactive else 'true'}">
        {'הסתר לא פעילים / Hide Inactive' if show_inactive else 'הצג לא פעילים / Show Inactive'}
      </a>
    </div>
    """
    
    # Build table rows
    table_rows = []
    for emp in employees:
        employee_id = emp.get("employee_id")
        name = escape(emp.get("name") or "")
        phone = escape(emp.get("phone") or "")
        role = escape(emp.get("role") or "")
        notes = escape(emp.get("notes") or "")
        is_active = emp.get("is_active", True)
        
        active_badge = (
            '<span class="badge bg-success">פעיל / Active</span>' if is_active
            else '<span class="badge bg-secondary">לא פעיל / Inactive</span>'
        )
        
        table_rows.append(f"""
            <tr>
              <td>{name}</td>
              <td>{phone}</td>
              <td>{role}</td>
              <td class="text-break">{notes}</td>
              <td>{active_badge}</td>
              <td class="text-nowrap">
                <a class="btn btn-sm btn-outline-secondary" href="/ui/employees/{employee_id}/edit">ערוך / Edit</a>
                <form method="post" action="/ui/employees/{employee_id}/delete" class="d-inline ms-1" 
                      onsubmit="return confirm('האם למחוק עובד זה?');">
                  <button class="btn btn-sm btn-outline-danger" type="submit">מחק / Delete</button>
                </form>
              </td>
            </tr>
        """)
    
    table_body = "".join(table_rows) or """
        <tr>
          <td colspan="6" class="text-center text-muted">אין עובדים / No employees yet.</td>
        </tr>
    """
    
    table = f"""
    <div class="card shadow-sm">
      <div class="card-header bg-secondary text-white">עובדים / Employees</div>
      <div class="card-body">
        {filter_toggle}
        <div class="table-responsive">
          <table class="table table-striped align-middle mb-0">
            <thead>
              <tr>
                <th scope="col">שם / Name</th>
                <th scope="col">Phone</th>
                <th scope="col">תפקיד / Role</th>
                <th scope="col">Notes</th>
                <th scope="col">סטטוס / Status</th>
                <th scope="col">Actions</th>
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
    
    html = _render_page("Employee Management", add_form + table)
    return HTMLResponse(content=html)


@router.post("/ui/employees")
async def create_employee(
    name: str = Form(...),
    phone: str = Form(...),
    role: str | None = Form(None),
    notes: str | None = Form(None),
    hoh: HOHService = Depends(get_hoh_service),
):
    """Create a new employee."""
    hoh.create_employee(
        org_id=1,
        name=name.strip(),
        phone=phone.strip(),
        role=role.strip() if role else None,
        notes=notes.strip() if notes else None,
        is_active=True,
    )
    return RedirectResponse(url="/ui/employees", status_code=303)


@router.get("/ui/employees/{employee_id}/edit", response_class=HTMLResponse)
async def edit_employee_form(
    employee_id: int,
    hoh: HOHService = Depends(get_hoh_service)
) -> HTMLResponse:
    """Show edit form for an employee."""
    employee = hoh.get_employee(org_id=1, employee_id=employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    name = escape(employee.get("name") or "")
    phone = escape(employee.get("phone") or "")
    role = escape(employee.get("role") or "")
    notes = escape(employee.get("notes") or "")
    
    form = f"""
    <div class="row justify-content-center">
      <div class="col-lg-6">
        <div class="card shadow-sm">
          <div class="card-header bg-primary text-white">ערוך עובד / Edit Employee</div>
          <div class="card-body">
            <form method="post" action="/ui/employees/{employee_id}/edit">
              <div class="mb-3">
                <label class="form-label" for="name">שם / Name</label>
                <input class="form-control" id="name" name="name" type="text" value="{name}" required>
              </div>
              <div class="mb-3">
                <label class="form-label" for="phone">Phone</label>
                <input class="form-control" id="phone" name="phone" type="text" value="{phone}" required>
              </div>
              <div class="mb-3">
                <label class="form-label" for="role">תפקיד / Role</label>
                <input class="form-control" id="role" name="role" type="text" value="{role}">
              </div>
              <div class="mb-3">
                <label class="form-label" for="notes">Notes</label>
                <textarea class="form-control" id="notes" name="notes" rows="3">{notes}</textarea>
              </div>
              <div class="d-flex justify-content-end">
                <a class="btn btn-outline-secondary me-2" href="/ui/employees">ביטול / Cancel</a>
                <button class="btn btn-primary" type="submit">שמור / Save</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
    """
    
    html = _render_page("Edit Employee", form)
    return HTMLResponse(content=html)


@router.post("/ui/employees/{employee_id}/edit")
async def update_employee(
    employee_id: int,
    name: str = Form(...),
    phone: str = Form(...),
    role: str | None = Form(None),
    notes: str | None = Form(None),
    hoh: HOHService = Depends(get_hoh_service),
):
    """Update an employee."""
    hoh.update_employee(
        org_id=1,
        employee_id=employee_id,
        name=name.strip(),
        phone=phone.strip(),
        role=role.strip() if role else None,
        notes=notes.strip() if notes else None,
    )
    return RedirectResponse(url="/ui/employees", status_code=303)


@router.post("/ui/employees/{employee_id}/delete")
async def delete_employee(
    employee_id: int,
    hoh: HOHService = Depends(get_hoh_service)
):
    """Soft delete an employee (set is_active=false)."""
    hoh.soft_delete_employee(org_id=1, employee_id=employee_id)
    return RedirectResponse(url="/ui/employees", status_code=303)


# ==========================================
# SHIFT ORGANIZER
# ==========================================

@router.get("/ui/shift-organizer")
async def shift_organizer_page(
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    """Shift Organizer UI - month-based shift scheduling."""
    from datetime import date
    from calendar import monthrange
    import json
    
    # Default to current month if not specified
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month
    
    # Get month name
    import calendar
    month_name = calendar.month_name[month]
    
    # Calculate prev/next month
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    body = f"""
    <div class="row mb-3">
      <div class="col">
        <h2>Shift Organizer - {month_name} {year}</h2>
      </div>
    </div>
    
    <div class="row mb-3">
      <div class="col">
        <div class="btn-group" role="group">
          <a href="/ui/shift-organizer?year={prev_year}&month={prev_month}" class="btn btn-outline-secondary">← Previous Month</a>
          <a href="/ui/shift-organizer" class="btn btn-outline-secondary">Current Month</a>
          <a href="/ui/shift-organizer?year={next_year}&month={next_month}" class="btn btn-outline-secondary">Next Month →</a>
        </div>
      </div>
      <div class="col text-end">
        <button id="generateBtn" class="btn btn-primary me-2">
          <span class="spinner-border spinner-border-sm d-none" role="status"></span>
          Generate Shifts
        </button>
        <button id="saveBtn" class="btn btn-success" disabled>
          <span class="spinner-border spinner-border-sm d-none" role="status"></span>
          Save to Database
        </button>
      </div>
    </div>
    
    <!-- Employee Stats -->
    <div id="employeeStats" class="row mb-3 d-none">
      <div class="col">
        <div class="card">
          <div class="card-header">
            <h5 class="mb-0">Employee Statistics</h5>
          </div>
          <div class="card-body">
            <table class="table table-sm">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Total Shifts</th>
                  <th>Weekend Shifts</th>
                </tr>
              </thead>
              <tbody id="statsBody">
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Events and Slots -->
    <div id="eventsContainer">
      <div class="text-center py-5">
        <div class="spinner-border" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
        <p class="mt-2">Loading events...</p>
      </div>
    </div>
    
    <script>
    const ORG_ID = 1;
    const YEAR = {year};
    const MONTH = {month};
    
    let currentData = null;
    let generatedSlots = null;
    let employees = [];
    let eventsById = {{}};
    
    function formatDateTimeLocal(value) {{
      if (!value) return '';
      const date = new Date(value);
      return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16);
    }}
    
    function buildEmployeeOptions(selectedId) {{
      return '<option value=\"\">-- Select Employee --</option>' + employees.map(emp => `
        <option value=\"${{emp.employee_id}}\" ${{selectedId === emp.employee_id ? 'selected' : ''}}>
          ${{emp.name}}
        </option>
      `).join('');
    }}
    
    // Load initial data
    async function loadMonthData() {{
      try {{
        const response = await fetch(`/shift-organizer/month?org_id=${{ORG_ID}}&year=${{YEAR}}&month=${{MONTH}}`);
        const data = await response.json();
        currentData = data;
        employees = data.employees;
        eventsById = Object.fromEntries((data.events || []).map(ev => [ev.event_id, ev]));
        renderEvents(data);
        renderStats(data.employee_stats);
      }} catch (error) {{
        console.error('Error loading data:', error);
        document.getElementById('eventsContainer').innerHTML = `
          <div class="alert alert-danger">
            <strong>Error:</strong> Failed to load events. ${{error.message}}
          </div>
        `;
      }}
    }}
    
    function renderStats(stats) {{
      if (!stats || stats.length === 0) {{
        document.getElementById('employeeStats').classList.add('d-none');
        return;
      }}
      
      document.getElementById('employeeStats').classList.remove('d-none');
      const tbody = document.getElementById('statsBody');
      tbody.innerHTML = stats.map(s => `
        <tr>
          <td>${{s.employee_name}}</td>
          <td>${{s.total_shifts}}</td>
          <td>${{s.weekend_shifts}}</td>
        </tr>
      `).join('');
    }}
    
    function renderEvents(data) {{
      const container = document.getElementById('eventsContainer');
      
      if (!data.events || data.events.length === 0) {{
        container.innerHTML = `
          <div class="alert alert-info">
            No events found for this month.
          </div>
        `;
        return;
      }}
      
      // Group shifts by event
      const shiftsByEvent = {{}};
      (data.shifts || []).forEach(shift => {{
        if (!shiftsByEvent[shift.event_id]) {{
          shiftsByEvent[shift.event_id] = [];
        }}
        shiftsByEvent[shift.event_id].push(shift);
      }});
      
      container.innerHTML = data.events.map(event => {{
        const eventShifts = shiftsByEvent[event.event_id] || [];
        return renderEvent(event, eventShifts);
      }}).join('');
    }}
    
    function renderEvent(event, shifts) {{
      const eventDate = new Date(event.event_date + 'T00:00:00');
      const dateStr = eventDate.toLocaleDateString('en-GB');
      const showTime = event.show_time ? new Date(event.show_time).toLocaleTimeString('en-GB', {{hour: '2-digit', minute: '2-digit'}}) : '-';
      const loadInTime = event.load_in_time ? new Date(event.load_in_time).toLocaleTimeString('en-GB', {{hour: '2-digit', minute: '2-digit'}}) : '-';
      
      return `
        <div class="card mb-3 event-card" data-event-id="${{event.event_id}}">
          <div class="card-header">
            <div class="row align-items-center">
              <div class="col-md-3">
                <strong>${{event.name}}</strong>
              </div>
              <div class="col-md-2">
                <small class="text-muted">Date:</small> ${{dateStr}}
              </div>
              <div class="col-md-2">
                <small class="text-muted">Show:</small> ${{showTime}}
              </div>
              <div class="col-md-2">
                <small class="text-muted">Load In:</small> ${{loadInTime}}
              </div>
              <div class="col-md-3">
                ${{event.notes ? `<small class="text-muted">${{event.notes}}</small>` : ''}}
              </div>
            </div>
            <div class="text-end mt-2">
              <button class="btn btn-sm btn-outline-primary" onclick="addSlot(${{event.event_id}})">
                + Add Shift
              </button>
            </div>
          </div>
          <div class="card-body">
            <div class="slots-container" data-event-id="${{event.event_id}}">
              ${{shifts.map((shift, idx) => renderSlot(event.event_id, shift, idx)).join('')}}
              ${{shifts.length === 0 ? '<p class="text-muted">No shifts assigned yet. Click "Generate Shifts" to auto-assign or add manually.</p>' : ''}}
            </div>
          </div>
        </div>
      `;
    }}
    
    function renderSlot(eventId, shift, index) {{
      const startValue = formatDateTimeLocal(shift.start_at || shift.call_time);
      const endValue = formatDateTimeLocal(shift.end_at || shift.call_time);
      const isLocked = shift.is_locked || false;
      const lockIcon = isLocked ? '🔒' : '';
      
      return `
        <div class="row mb-2 align-items-center slot-row" 
             data-slot-index="${{index}}"
             data-event-id="${{eventId}}"
             data-start="${{shift.start_at || ''}}"
             data-end="${{shift.end_at || ''}}"
             data-is-locked="${{isLocked}}"
             data-shift-id="${{shift.shift_id || ''}}"
             data-shift-type="${{shift.shift_type || ''}}">
          <div class="col-md-3">
            <input type="datetime-local" class="form-control form-control-sm start-at" value="${{startValue}}" ${{isLocked ? 'disabled' : ''}}>
          </div>
          <div class="col-md-3">
            <input type="datetime-local" class="form-control form-control-sm end-at" value="${{endValue}}" ${{isLocked ? 'disabled' : ''}}>
          </div>
          <div class="col-md-3">
            <select class="form-select form-select-sm employee-select" ${{isLocked ? 'disabled' : ''}}>
              ${{buildEmployeeOptions(shift.employee_id)}}
            </select>
          </div>
          <div class="col-md-2">
            <span class="badge bg-${{isLocked ? 'warning' : 'secondary'}}">${{lockIcon}} ${{shift.shift_type || 'shift'}}</span>
          </div>
          <div class="col-md-1 text-end">
            <button class="btn btn-sm btn-outline-danger" onclick="removeSlot(this)" ${{isLocked ? 'disabled' : ''}}>✕</button>
          </div>
        </div>
      `;
    }}
    
    function removeSlot(btn) {{
      btn.closest('.slot-row').remove();
      document.getElementById('saveBtn').disabled = false;
    }}
    
    document.addEventListener('change', (event) => {{
      if (event.target.closest('.slot-row')) {{
        document.getElementById('saveBtn').disabled = false;
      }}
    }});
    
    function getDefaultTimes(eventId) {{
      const event = eventsById[eventId];
      const now = new Date();
      if (!event) {{
        const fallbackEnd = new Date(now.getTime() + 2 * 60 * 60 * 1000);
        return {{ start: now, end: fallbackEnd }};
      }}
      
      const baseDate = new Date(event.event_date + 'T00:00:00');
      const start = event.show_time ? new Date(event.show_time) :
                    (event.load_in_time ? new Date(event.load_in_time) : new Date(baseDate.setHours(18, 0, 0, 0)));
      const end = new Date(start.getTime() + 4 * 60 * 60 * 1000);
      return {{ start, end }};
    }}
    
    function addSlot(eventId) {{
      const container = document.querySelector(`.slots-container[data-event-id="${{eventId}}"]`);
      if (!container) return;
      
      const times = getDefaultTimes(eventId);
      const newShift = {{
        start_at: times.start.toISOString(),
        end_at: times.end.toISOString(),
        employee_id: null,
        shift_type: 'shift',
        is_locked: false,
        shift_id: null,
      }};
      
      const newIndex = container.querySelectorAll('.slot-row').length;
      container.insertAdjacentHTML('beforeend', renderSlot(eventId, newShift, newIndex));
      document.getElementById('saveBtn').disabled = false;
    }}
    
    // Generate Shifts
    document.getElementById('generateBtn').addEventListener('click', async () => {{
      const btn = document.getElementById('generateBtn');
      const spinner = btn.querySelector('.spinner-border');
      
      btn.disabled = true;
      spinner.classList.remove('d-none');
      
      try {{
        const response = await fetch('/shift-organizer/generate', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            org_id: ORG_ID,
            year: YEAR,
            month: MONTH
          }})
        }});
        
        const result = await response.json();
        generatedSlots = result.slots;
        
        // Render generated slots
        renderGeneratedSlots(result);
        renderStats(Object.values(result.employee_stats));
        
        // Enable save button
        document.getElementById('saveBtn').disabled = false;
        
        alert(`Generated ${{result.slots.length}} shift assignments!`);
      }} catch (error) {{
        console.error('Error generating shifts:', error);
        alert('Failed to generate shifts: ' + error.message);
      }} finally {{
        btn.disabled = false;
        spinner.classList.add('d-none');
      }}
    }});
    
    function renderGeneratedSlots(result) {{
      // Group slots by event
      const slotsByEvent = {{}};
      result.slots.forEach(slot => {{
        if (!slotsByEvent[slot.event_id]) {{
          slotsByEvent[slot.event_id] = [];
        }}
        slotsByEvent[slot.event_id].push(slot);
      }});
      
      // Update each event's slots
      Object.entries(slotsByEvent).forEach(([eventId, slots]) => {{
        const container = document.querySelector(`.slots-container[data-event-id="${{eventId}}"]`);
        if (container) {{
          container.innerHTML = slots.map((slot, idx) => renderGeneratedSlot(eventId, slot, idx)).join('');
        }}
      }});
    }}
    
    function renderGeneratedSlot(eventId, slot, index) {{
      const employeeOptions = buildEmployeeOptions(slot.suggested_employee_id);
      
      const isUnfilled = !slot.suggested_employee_id;
      const bgClass = isUnfilled ? 'bg-danger text-white' : '';
      const reason = slot.unfilled_reason || '';
      
      return `
        <div class="row mb-2 align-items-center slot-row ${{bgClass}}" 
             data-slot-index="${{index}}"
             data-event-id="${{eventId}}"
             data-start="${{slot.start_at}}"
             data-end="${{slot.end_at}}"
             data-is-locked="false"
             data-shift-type="${{slot.shift_type || 'shift'}}"
             title="${{reason}}">
          <div class="col-md-3">
            <input type="datetime-local" class="form-control form-control-sm start-at" value="${{formatDateTimeLocal(slot.start_at)}}">
          </div>
          <div class="col-md-3">
            <input type="datetime-local" class="form-control form-control-sm end-at" value="${{formatDateTimeLocal(slot.end_at)}}">
          </div>
          <div class="col-md-3">
            <select class="form-select form-select-sm employee-select">
              ${{employeeOptions}}
            </select>
          </div>
          <div class="col-md-2 text-end">
            <button class="btn btn-sm btn-outline-danger" onclick="removeSlot(this)">✕</button>
          </div>
        </div>
      `;
    }}
    
    // Save Shifts
    document.getElementById('saveBtn').addEventListener('click', async () => {{
      const btn = document.getElementById('saveBtn');
      const spinner = btn.querySelector('.spinner-border');
      
      btn.disabled = true;
      spinner.classList.remove('d-none');
      
      try {{
        // Collect all slots from UI
        const slots = [];
        document.querySelectorAll('.slot-row').forEach(row => {{
          const eventId = parseInt(row.dataset.eventId);
          const employeeSelect = row.querySelector('.employee-select');
          const employeeId = employeeSelect && employeeSelect.value ? parseInt(employeeSelect.value) : null;
          const startInput = row.querySelector('.start-at');
          const endInput = row.querySelector('.end-at');
          const startAt = startInput && startInput.value ? new Date(startInput.value).toISOString() : null;
          const endAt = endInput && endInput.value ? new Date(endInput.value).toISOString() : null;
          const shiftId = row.dataset.shiftId ? parseInt(row.dataset.shiftId) : null;
          const shiftType = row.dataset.shiftType || null;
          const isLocked = row.dataset.isLocked === 'true';
          
          if (employeeId && startAt && endAt) {{
            slots.push({{
              event_id: eventId,
              employee_id: employeeId,
              start_at: startAt,
              end_at: endAt,
              shift_id: shiftId,
              shift_type: shiftType,
              is_locked: isLocked
            }});
          }}
        }});
        
        const eventIds = Array.from(document.querySelectorAll('.event-card'))
          .map(card => parseInt(card.dataset.eventId))
          .filter(id => !Number.isNaN(id));
        
        const response = await fetch('/shift-organizer/save', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            org_id: ORG_ID,
            year: YEAR,
            month: MONTH,
            event_ids: eventIds,
            slots: slots
          }})
        }});
        
        const result = await response.json();
        
        // Reload data
        await loadMonthData();
        
        alert(`Saved ${{slots.length}} shift assignments!`);
        btn.disabled = true;
      }} catch (error) {{
        console.error('Error saving shifts:', error);
        alert('Failed to save shifts: ' + error.message);
      }} finally {{
        spinner.classList.add('d-none');
      }}
    }});
    
    // Initial load
    loadMonthData();
    </script>
    """
    
    return HTMLResponse(_render_page("Shift Organizer", body))


@router.get("/ui/availability")
async def availability_page(
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    """Employee Availability Management UI."""
    from datetime import date
    import calendar
    
    # Default to next month
    today = date.today()
    if year is None or month is None:
        # Default to next month
        next_month = today.month + 1 if today.month < 12 else 1
        next_year = today.year if today.month < 12 else today.year + 1
        year = next_year
        month = next_month
    
    month_name = calendar.month_name[month]
    
    # Calculate prev/next month
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    body = f"""
    <div class="row mb-3">
      <div class="col">
        <h2>Employee Availability - {month_name} {year}</h2>
        <p class="text-muted">Mark periods when employees are unavailable for shifts</p>
      </div>
    </div>
    
    <div class="row mb-3">
      <div class="col">
        <div class="btn-group" role="group">
          <a href="/ui/availability?year={prev_year}&month={prev_month}" class="btn btn-outline-secondary">← Previous Month</a>
          <a href="/ui/availability" class="btn btn-outline-secondary">Next Month (Default)</a>
          <a href="/ui/availability?year={next_year}&month={next_month}" class="btn btn-outline-secondary">Following Month →</a>
        </div>
      </div>
      <div class="col text-end">
        <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#addUnavailabilityModal">
          + Add Unavailability
        </button>
      </div>
    </div>
    
    <!-- Unavailability List -->
    <div id="unavailabilityContainer">
      <div class="text-center py-5">
        <div class="spinner-border" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
      </div>
    </div>
    
    <!-- Add Unavailability Modal -->
    <div class="modal fade" id="addUnavailabilityModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Add Unavailability</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <form id="unavailabilityForm">
              <div class="mb-3">
                <label class="form-label">Employee</label>
                <select class="form-select" id="employeeSelect" required>
                  <option value="">-- Select Employee --</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Start Date & Time</label>
                <input type="datetime-local" class="form-control" id="startAt" required>
              </div>
              <div class="mb-3">
                <label class="form-label">End Date & Time</label>
                <input type="datetime-local" class="form-control" id="endAt" required>
              </div>
              <div class="mb-3">
                <label class="form-label">Reason (Optional)</label>
                <textarea class="form-control" id="note" rows="2"></textarea>
              </div>
            </form>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-primary" id="saveUnavailabilityBtn">Save</button>
          </div>
        </div>
      </div>
    </div>
    
    <script>
    const ORG_ID = 1;
    const YEAR = {year};
    const MONTH = {month};
    
    let employees = [];
    let unavailability = [];
    
    async function loadEmployees() {{
      try {{
        // Use the shift-organizer endpoint to get employees
        const response = await fetch(`/shift-organizer/month?org_id=${{ORG_ID}}&year=${{YEAR}}&month=${{MONTH}}`);
        const data = await response.json();
        employees = data.employees;
        
        // Populate employee dropdown
        const select = document.getElementById('employeeSelect');
        select.innerHTML = '<option value="">-- Select Employee --</option>' +
          employees.map(emp => `<option value="${{emp.employee_id}}">${{emp.name}}</option>`).join('');
      }} catch (error) {{
        console.error('Error loading employees:', error);
      }}
    }}
    
    async function loadUnavailability() {{
      try {{
        const response = await fetch(`/availability/month?org_id=${{ORG_ID}}&year=${{YEAR}}&month=${{MONTH}}`);
        const data = await response.json();
        unavailability = data.unavailability || [];
        renderUnavailability();
      }} catch (error) {{
        console.error('Error loading unavailability:', error);
        document.getElementById('unavailabilityContainer').innerHTML = `
          <div class="alert alert-danger">
            Failed to load unavailability data: ${{error.message}}
          </div>
        `;
      }}
    }}
    
    function renderUnavailability() {{
      const container = document.getElementById('unavailabilityContainer');
      
      if (unavailability.length === 0) {{
        container.innerHTML = `
          <div class="alert alert-info">
            No unavailability blocks for this month. Employees are available for all shifts.
          </div>
        `;
        return;
      }}
      
      // Group by employee
      const byEmployee = {{}};
      unavailability.forEach(u => {{
        const empName = u.employee_name || 'Unknown';
        if (!byEmployee[empName]) {{
          byEmployee[empName] = [];
        }}
        byEmployee[empName].push(u);
      }});
      
      container.innerHTML = `
        <div class="list-group">
          ${{Object.entries(byEmployee).map(([empName, blocks]) => `
            <div class="list-group-item">
              <h6>${{empName}}</h6>
              ${{blocks.map(block => {{
                const startDate = new Date(block.start_at);
                const endDate = new Date(block.end_at);
                const startStr = startDate.toLocaleString('en-GB', {{dateStyle: 'short', timeStyle: 'short'}});
                const endStr = endDate.toLocaleString('en-GB', {{dateStyle: 'short', timeStyle: 'short'}});
                
                return `
                  <div class="d-flex justify-content-between align-items-start mb-2">
                    <div>
                      <strong>${{startStr}}</strong> → <strong>${{endStr}}</strong>
                      ${{block.note ? `<br><small class="text-muted">${{block.note}}</small>` : ''}}
                    </div>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteUnavailability(${{block.unavailability_id}})">
                      Delete
                    </button>
                  </div>
                `;
              }}).join('')}}
            </div>
          `).join('')}}
        </div>
      `;
    }}
    
    async function deleteUnavailability(id) {{
      if (!confirm('Delete this unavailability block?')) return;
      
      try {{
        await fetch(`/availability/${{id}}?org_id=${{ORG_ID}}`, {{
          method: 'DELETE'
        }});
        await loadUnavailability();
      }} catch (error) {{
        console.error('Error deleting:', error);
        alert('Failed to delete: ' + error.message);
      }}
    }}
    
    document.getElementById('saveUnavailabilityBtn').addEventListener('click', async () => {{
      const form = document.getElementById('unavailabilityForm');
      if (!form.checkValidity()) {{
        form.reportValidity();
        return;
      }}
      
      const employeeId = parseInt(document.getElementById('employeeSelect').value);
      const startAt = document.getElementById('startAt').value;
      const endAt = document.getElementById('endAt').value;
      const note = document.getElementById('note').value;
      
      try {{
        await fetch('/availability', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            org_id: ORG_ID,
            employee_id: employeeId,
            start_at: startAt,
            end_at: endAt,
            note: note || null
          }})
        }});
        
        // Close modal and reload
        const modal = bootstrap.Modal.getInstance(document.getElementById('addUnavailabilityModal'));
        modal.hide();
        form.reset();
        await loadUnavailability();
      }} catch (error) {{
        console.error('Error saving:', error);
        alert('Failed to save: ' + error.message);
      }}
    }});
    
    // Initial load
    loadEmployees();
    loadUnavailability();
    </script>
    """
    
    return HTMLResponse(_render_page("Employee Availability", body))
