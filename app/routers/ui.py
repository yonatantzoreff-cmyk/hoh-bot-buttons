"""Minimal Bootstrap-based UI for managing events via Postgres."""
import logging
from datetime import timezone
from html import escape
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService

router = APIRouter()
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def _strip_timezone(dt):
    """Drop timezone info while keeping the clock time as-is."""

    if not dt:
        return None

    return dt.replace(tzinfo=None)


def _to_israel_time(dt):
    """Convert a timestamp (assumed UTC if naive) to Israel time."""

    if not dt:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(ISRAEL_TZ)


def _render_page(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <title>{escape(title)}</title>
        <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\" rel=\"stylesheet\" integrity=\"sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH\" crossorigin=\"anonymous\">
        <link href=\"https://cdn.datatables.net/1.13.8/css/dataTables.bootstrap5.min.css\" rel=\"stylesheet\">
        <link href=\"https://cdn.datatables.net/colreorder/1.6.3/css/colReorder.bootstrap5.min.css\" rel=\"stylesheet\">
      </head>
      <body class=\"bg-light\">
        <nav class=\"navbar navbar-expand-lg navbar-dark bg-dark\">
          <div class=\"container-fluid\">
            <a class=\"navbar-brand\" href=\"/ui\">HOH BOT – Events</a>
            <div>
              <a class=\"btn btn-outline-light btn-sm me-2\" href=\"/ui\">Add Event</a>
              <a class=\"btn btn-outline-light btn-sm\" href=\"/ui/events\">View Events</a>
              <a class=\"btn btn-outline-light btn-sm ms-2\" href=\"/ui/contacts\">Contacts</a>
              <a class=\"btn btn-light btn-sm ms-2\" href=\"/ui/messages\">Messages</a>
              <a class=\"btn btn-outline-success btn-sm ms-2\" href=\"/ui/calendar-import\">Import Calendar</a>
            </div>
          </div>
        </nav>
        <main class=\"container py-4\">
          {body}
        </main>
        <script src=\"https://code.jquery.com/jquery-3.7.1.min.js\" integrity=\"sha256-3gJwYpJPgH+U5Q5J5r3bJfFqvF8S2RkG8h6fWK3kNlc=\" crossorigin=\"anonymous\"></script>
        <script src=\"https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js\"></script>
        <script src=\"https://cdn.datatables.net/1.13.8/js/dataTables.bootstrap5.min.js\"></script>
        <script src=\"https://cdn.datatables.net/colreorder/1.6.3/js/dataTables.colReorder.min.js\"></script>
        <script src=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js\" crossorigin=\"anonymous\"></script>
      </body>
    </html>
    """


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
            show_time = _strip_timezone(message.get("show_time"))
            event_group = {
                "event_id": event_id,
                "event_name": message.get("event_name") or "Unassigned",
                "event_date_display": event_date.strftime("%Y-%m-%d") if event_date else "",
                "show_time_display": show_time.strftime("%H:%M") if show_time else "",
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

    table_rows = []
    for row in events:
        event_date = row.get("event_date")
        show_time = _strip_timezone(row.get("show_time"))
        load_in_time = _strip_timezone(row.get("load_in_time"))
        created_at = _to_israel_time(row.get("created_at"))
        hall_label = row.get("hall_name") or (
            f"Hall #{row['hall_id']}" if row.get("hall_id") is not None else ""
        )
        date_display = event_date.strftime("%Y-%m-%d") if event_date else ""
        time_display = show_time.strftime("%H:%M") if show_time else ""
        load_in_display = load_in_time.strftime("%H:%M") if load_in_time else ""
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

        table_rows.append(
            """
            <tr>
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
              <td>{created_at}</td>
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
            """.format(
                name=escape(row.get("name") or ""),
                date=escape(date_display),
                time=escape(time_display),
                load_in=escape(load_in_display),
                hall=escape(hall_label or ""),
                status=escape(status),
                delivery_status=escape(delivery_status_display),
                delivery_status_class=delivery_status_class,
                notes=escape(row.get("notes") or ""),
                producer_phone=escape(producer_display),
                technical_phone=escape(technical_phone),
                created_at=escape(created_at_display),
                event_id=row.get("event_id"),
                whatsapp_btn_class=whatsapp_btn_class,
                sent_indicator=sent_indicator,
            )
        )

    table_body = "".join(table_rows) or """
        <tr>
          <td colspan=\"12\" class=\"text-center text-muted\">No events yet.</td>
        </tr>
    """

    table_template = """
    <div class=\"card\">
      <div class=\"card-header bg-secondary text-white\">Events</div>
      <div class=\"card-body\">
        <div class=\"table-responsive\">
          <table id=\"events-table\" class=\"table table-striped align-middle\">
            <thead>
              <tr>
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
                <th scope=\"col\">Created At</th>
                <th scope=\"col\">Actions</th>
              </tr>
            </thead>
            <tbody>
              {table_body}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    <script>
      document.addEventListener("DOMContentLoaded", function () {{
        const tableElement = document.getElementById("events-table");
        if (!tableElement || !window.jQuery) {{
          return;
        }}

        const $table = window.jQuery(tableElement);
        const currentHeaders = Array.from(
          tableElement.querySelectorAll("thead th")
        ).map((th) => th.textContent.trim());
        const stateKey = `DataTables_${{tableElement.id}}_${{window.location.pathname}}`;

        $table.DataTable({{
          stateSave: true,
          stateDuration: -1,
          colReorder: true,
          order: [],
          stateSaveParams: function (_settings, data) {{
            data.columnHeaders = currentHeaders;
          }},
          stateLoadCallback: function (_settings) {{
            const savedState = localStorage.getItem(stateKey);
            if (!savedState) {{
              return null;
            }}

            try {{
              const parsedState = JSON.parse(savedState);
              if (
                Array.isArray(parsedState.columnHeaders) &&
                parsedState.columnHeaders.join("|||") !==
                  currentHeaders.join("|||")
              ) {{
                localStorage.removeItem(stateKey);
                return null;
              }}

              return parsedState;
            }} catch (error) {{
              console.warn("Failed to load saved table state", error);
              return null;
            }}
          }},
        }});
      }});
    </script>
    """

    table = table_template.format(table_body=table_body)

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
    show_time = event.get("show_time")
    load_in_time = event.get("load_in_time")

    event_date_str = event_date.strftime("%Y-%m-%d") if event_date else ""
    show_time_str = show_time.strftime("%H:%M") if show_time else ""
    load_in_time_str = load_in_time.strftime("%H:%M") if load_in_time else ""

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
        
        return `
          <tr class="${rowClass}">
            <td>${event.row_index}</td>
            <td>${event.date || '-'}</td>
            <td>${event.show_time || '-'}</td>
            <td>${escape(event.name || '-')}</td>
            <td>${event.load_in || '-'}</td>
            <td>${escape(event.event_series || '-')}</td>
            <td>${escape(event.producer_name || '-')}</td>
            <td>${escape(event.producer_phone || '-')}</td>
            <td>${escape(event.notes || '-')}</td>
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
