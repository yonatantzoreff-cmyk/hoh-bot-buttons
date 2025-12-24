import pytest
import os
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from app.constants import EVENT_STATUS_OPTIONS

# Prevent import-time failures from missing Twilio credentials
os.environ.setdefault("TWILIO_ACCOUNT_SID", "test")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test")
os.environ.setdefault("CONTENT_SID_INIT", "test")
os.environ.setdefault("CONTENT_SID_RANGES", "test")
os.environ.setdefault("CONTENT_SID_HALVES", "test")
os.environ.setdefault("CONTENT_SID_CONFIRM", "test")
os.environ.setdefault("CONTENT_SID_NOT_SURE", "test")
os.environ.setdefault("CONTENT_SID_CONTACT", "test")
os.environ.setdefault("CONTENT_SID_SHIFT_REMINDER", "test")
os.environ.setdefault("CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT", "test")

from app.routers import ui  # noqa: E402


class DummyEvents:
    def __init__(self, should_update: bool = True):
        self.should_update = should_update
        self.calls: list[dict] = []

    def update_event_status(self, *, event_id: int, status: str, org_id: int) -> bool:
        self.calls.append({"event_id": event_id, "status": status, "org_id": org_id})
        return self.should_update


class DummyService:
    def __init__(self, events_repo: DummyEvents):
        self.events = events_repo


@pytest.mark.anyio
async def test_update_event_status_success():
    events_repo = DummyEvents(should_update=True)
    hoh = DummyService(events_repo)

    response = await ui.update_event_status(
        event_id=5,
        status=EVENT_STATUS_OPTIONS[0],
        hoh=hoh,
    )

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers.get("location") == "/ui/events"
    assert events_repo.calls == [
        {"event_id": 5, "status": EVENT_STATUS_OPTIONS[0], "org_id": 1}
    ]


@pytest.mark.anyio
async def test_update_event_status_invalid_status():
    events_repo = DummyEvents(should_update=True)
    hoh = DummyService(events_repo)

    with pytest.raises(HTTPException) as exc_info:
        await ui.update_event_status(
            event_id=5,
            status="invalid-status",
            hoh=hoh,
        )

    assert exc_info.value.status_code == 400
    assert events_repo.calls == []


@pytest.mark.anyio
async def test_update_event_status_not_found():
    events_repo = DummyEvents(should_update=False)
    hoh = DummyService(events_repo)

    with pytest.raises(HTTPException) as exc_info:
        await ui.update_event_status(
            event_id=5,
            status=EVENT_STATUS_OPTIONS[0],
            hoh=hoh,
        )

    assert exc_info.value.status_code == 404
