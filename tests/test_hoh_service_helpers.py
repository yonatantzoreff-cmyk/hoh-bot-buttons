import os
from datetime import date, datetime, time, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "test-sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-token")
os.environ.setdefault("TWILIO_MESSAGING_SERVICE_SID", "MGXXXX")

from app.hoh_service import HOHService


def test_parse_action_payload_variants():
    service = HOHService()

    assert service._parse_action_payload("SLOT_2_EVT_5") == {
        "action": "SLOT",
        "event_id": 5,
        "slot_index": 2,
    }
    assert service._parse_action_payload("CONFIRM_SLOT_EVT_9") == {
        "action": "CONFIRM_SLOT",
        "event_id": 9,
        "slot_index": None,
    }
    assert service._parse_action_payload("NOT_CONTACT_EVT_3") == {
        "action": "NOT_CONTACT",
        "event_id": 3,
        "slot_index": None,
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
    service = HOHService()
    event = {
        "event_id": 42,
        "show_time": datetime.combine(
            date(2024, 8, 10), time(20, 0), tzinfo=timezone.utc
        ),
    }

    slots = service._build_slots(event)

    assert all(slot["event_id"] == 42 for slot in slots)
    assert slots[0]["id"] == "SLOT_1_EVT_42"
    assert slots[0]["label"].count(":") == 1  # formatted as HH:MM
    assert any("SLOT_2_EVT_42" == slot["id"] for slot in slots)
