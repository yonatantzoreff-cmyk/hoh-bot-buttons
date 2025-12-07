"""Minimal Bootstrap-based UI for managing events via Postgres."""
import logging
from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService

router = APIRouter()
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")


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
              <a class=\"btn btn-light btn-sm ms-2\" href=\"/ui/messages\">Messages</a>
            </div>
          </div>
        </nav>
        <main class=\"container py-4\">
          {body}
        </main>
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
    await hoh.send_init_for_event(event_id=event_id, org_id=1)
    return RedirectResponse(url="/ui/events", status_code=303)


@router.get("/ui/events", response_class=HTMLResponse)
async def list_events(hoh: HOHService = Depends(get_hoh_service)) -> HTMLResponse:
    events = hoh.list_events_for_org(org_id=1)

    table_rows = []
    for row in events:
        event_date = row.get("event_date")
        show_time = row.get("show_time")
        load_in_time = row.get("load_in_time")
        created_at = row.get("created_at")
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
        producer_phone = row.get("producer_phone") or ""
        technical_phone = row.get("technical_phone") or ""

        table_rows.append(
            """
            <tr>
              <td>{name}</td>
              <td>{date}</td>
              <td>{time}</td>
              <td>{load_in}</td>
              <td>{hall}</td>
              <td>{status}</td>
              <td>{producer_phone}</td>
              <td>{technical_phone}</td>
              <td>{created_at}</td>
              <td class=\"text-nowrap\">
                <form method=\"post\" action=\"/ui/events/{event_id}/send-init\" class=\"d-inline\">
                  <button class=\"btn btn-sm btn-outline-primary\" type=\"submit\">Send INIT</button>
                </form>
                <a class=\"btn btn-sm btn-outline-secondary ms-1\" href=\"/ui/events/{event_id}/edit\">Edit</a>
                <form method=\"post\" action=\"/ui/events/{event_id}/delete\" class=\"d-inline ms-1\">
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
                producer_phone=escape(producer_phone),
                technical_phone=escape(technical_phone),
                created_at=escape(created_at_display),
                event_id=row.get("event_id"),
            )
        )

    table_body = "".join(table_rows) or """
        <tr>
          <td colspan=\"10\" class=\"text-center text-muted\">No events yet.</td>
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
                <th scope=\"col\">Name</th>
                <th scope=\"col\">Date</th>
                <th scope=\"col\">Show Time</th>
                <th scope=\"col\">Load In</th>
                <th scope=\"col\">Hall</th>
                <th scope=\"col\">Status</th>
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
    """

    html = _render_page("Events", table)
    return HTMLResponse(content=html)


@router.get("/ui/messages", response_class=HTMLResponse)
async def list_messages(
    request: Request, hoh: HOHService = Depends(get_hoh_service)
) -> HTMLResponse:
    rows = hoh.list_messages_with_events(org_id=1)

    grouped_events: dict[int | None, dict] = {}

    for row in rows:
        event_id = row.get("event_id")
        event_group = grouped_events.get(event_id)

        if not event_group:
            event_date = row.get("event_date")
            show_time = row.get("show_time")

            event_group = {
                "event_id": event_id,
                "event_name": row.get("event_name") or f"Event #{event_id}",
                "event_date": event_date,
                "event_date_display": event_date.strftime("%Y-%m-%d")
                if event_date
                else "",
                "show_time_display": show_time.strftime("%H:%M") if show_time else "",
                "messages": [],
            }
            grouped_events[event_id] = event_group

        contact_label = _contact_label(row.get("contact_name"), row.get("contact_phone"))
        direction = row.get("direction") or ""
        if direction == "incoming":
            from_display = contact_label
            to_display = "HOH BOT"
        else:
            from_display = "HOH BOT"
            to_display = contact_label

        timestamp = row.get("sent_at") or row.get("received_at") or row.get("created_at")
        timestamp_display = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else ""

        event_group["messages"].append(
            {
                "direction": direction,
                "from": from_display,
                "to": to_display,
                "body": row.get("body") or "",
                "timestamp": timestamp,
                "timestamp_display": timestamp_display,
            }
        )

    events = list(grouped_events.values())

    return templates.TemplateResponse(
        "ui/messages.html", {"request": request, "events": events}
    )
