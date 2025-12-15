import os
from datetime import date, datetime, time, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "test-sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-token")
os.environ.setdefault("TWILIO_MESSAGING_SERVICE_SID", "MGXXXX")
os.environ.setdefault("CONTENT_SID_INIT", "HXINIT")
os.environ.setdefault("CONTENT_SID_RANGES", "HXRANGE")
os.environ.setdefault("CONTENT_SID_HALVES", "HXHALF")
os.environ.setdefault("CONTENT_SID_CONFIRM", "HXCONFIRM")
os.environ.setdefault("CONTENT_SID_NOT_SURE", "HXNOTSURE")
os.environ.setdefault("CONTENT_SID_CONTACT", "HXCONTACT")
os.environ.setdefault("CONTENT_SID_SHIFT_REMINDER", "HXSHIFT")

from app.hoh_service import HOHService, _half_hour_slots_for_range
from app.utils.actions import parse_action_id


def test_parse_action_payload_variants():
    assert parse_action_id("HALF_3_EVT_7_RANGE_2") == {
        "type": "HALF",
        "event_id": 7,
        "half_index": 3,
        "range_id": 2,
    }
    assert parse_action_id("CONFIRM_SLOT_EVT_9") == {
        "type": "CONFIRM_SLOT",
        "event_id": 9,
    }
    assert parse_action_id("NOT_CONTACT_EVT_3") == {
        "type": "NOT_CONTACT",
        "event_id": 3,
    }


def test_build_followup_variables_use_event_and_contact_data():
    service = HOHService()
    event = {
        "name": "Spring Gala",
        "event_date": date(2024, 5, 1),
        "show_time": datetime(2024, 5, 1, 18, 30, tzinfo=timezone.utc),
    }
    contact = {"name": "Dana Producer"}

    variables = service._build_followup_variables(contact=contact, event=event)

    assert variables == {
        "producer_name": "Dana Producer",
        "event_name": "Spring Gala",
        "event_date": "01.05.2024",
        "show_time": "18:30",
    }


def test_build_slots_includes_event_context():
    slots = _half_hour_slots_for_range(2)

    assert len(slots) == 8
    assert slots[0] == "04:00"
    assert all(":" in slot for slot in slots)


def test_extract_contact_details_prefers_payload_data():
    service = HOHService()
    payload = {
        "Contacts[0][PhoneNumber]": "0501234567",
        "Contacts[0][Name]": "Tech Friend",
    }

    phone, name = service._extract_contact_details(payload, "")

    assert phone == "+972501234567"
    assert name == "Tech Friend"


def test_extract_contact_details_uses_body_as_fallback():
    service = HOHService()

    phone, name = service._extract_contact_details({}, "052-7654321 Moshe")

    assert phone == "+972527654321"
    assert name == "052-7654321 Moshe"


def test_download_media_text_handles_utf8_names(monkeypatch):
    service = HOHService()

    class DummyResponse:
        ok = True
        # Simulate Twilio returning Hebrew characters that would be mis-decoded
        # if the response encoding were treated as ISO-8859-1.
        content = "BEGIN:VCARD\nFN:יונתן היכל\nTEL:+972503001613\nEND:VCARD".encode(
            "utf-8"
        )
        encoding = "ISO-8859-1"

        @property
        def text(self):  # pragma: no cover - fallback path
            return self.content.decode(self.encoding, errors="replace")

    monkeypatch.setattr("app.hoh_service.requests.get", lambda *_, **__: DummyResponse())

    text = service._download_media_text("https://example.test/media")

    assert "יונתן היכל" in text


def test_list_events_includes_latest_delivery_status(monkeypatch):
    service = HOHService()

    fake_events = [
        {
            "event_id": 1,
            "name": "Test Event",
            "event_date": date(2024, 1, 1),
            "show_time": datetime(2024, 1, 1, 18, 0, tzinfo=timezone.utc),
            "load_in_time": datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
            "hall_id": 2,
            "hall_name": "Main Hall",
            "status": "pending",
            "producer_contact_id": None,
            "technical_contact_id": None,
            "created_at": datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            "notes": "",
        },
        {
            "event_id": 2,
            "name": "No Message Event",
            "event_date": date(2024, 1, 2),
            "show_time": None,
            "load_in_time": None,
            "hall_id": None,
            "hall_name": None,
            "status": "draft",
            "producer_contact_id": None,
            "technical_contact_id": None,
            "created_at": datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
            "notes": None,
        },
    ]

    monkeypatch.setattr(
        service.events, "list_events_for_org", lambda org_id: fake_events
    )
    monkeypatch.setattr(
        service.messages, "get_latest_status_by_event", lambda org_id: {1: "delivered"}
    )
    monkeypatch.setattr(
        service.messages,
        "get_last_sent_at_for_content",
        lambda org_id, event_id, content_sid: None,
    )

    events = service.list_events_for_org(org_id=1)

    assert events[0]["latest_delivery_status"] == "delivered"
    assert events[1]["latest_delivery_status"] is None
