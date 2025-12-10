import asyncio
import os
from datetime import date, datetime, timezone

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


class DummyContacts:
    def get_or_create_by_phone(self, **_):
        return 1

    def get_contact_by_id(self, **_):  # pragma: no cover - unused in tests
        return {"phone": "+972500000000"}


class DummyEvents:
    def __init__(self):
        self.requested_ids = []

    def get_event_by_id(self, org_id: int, event_id: int):
        self.requested_ids.append((org_id, event_id))
        return {"event_id": event_id, "name": "Fallback Event"}


class DummyConversations:
    def __init__(self, conversation):
        self.conversation = conversation

    def get_open_conversation(self, **_):
        return self.conversation

    def create_conversation(self, **_):  # pragma: no cover - defensive
        raise AssertionError("Unexpected conversation creation")

    def get_recent_open_for_contact(self, **_):
        return self.conversation

    def get_most_recent_for_contact(self, **_):  # pragma: no cover - overridden per test
        return self.conversation


class DummyMessages:
    def __init__(self):
        self.logged = []

    def log_message(self, **payload):
        self.logged.append(payload)

    def log_delivery_status(self, **_):  # pragma: no cover - not exercised
        return None


def test_handle_webhook_falls_back_to_recent_conversation(monkeypatch):
    service = HOHService()
    conversation = {
        "conversation_id": 7,
        "event_id": 44,
        "pending_data_fields": {"last_range_id": 2},
    }

    service.contacts = DummyContacts()
    service.events = DummyEvents()
    service.conversations = DummyConversations(conversation)
    service.messages = DummyMessages()

    sent = []
    monkeypatch.setattr("app.hoh_service.twilio_client.send_text", lambda *args, **kwargs: sent.append(kwargs))

    payload = {"From": "+972500000001", "ButtonText": "Pick this"}

    asyncio.run(service.handle_whatsapp_webhook(payload, org_id=1))

    assert service.messages.logged
    assert service.messages.logged[0]["event_id"] == 44
    assert not sent


def test_handle_webhook_prompts_when_no_event_found(monkeypatch):
    service = HOHService()

    service.contacts = DummyContacts()
    service.events = DummyEvents()
    service.conversations = DummyConversations(None)
    service.messages = DummyMessages()

    sent = []
    monkeypatch.setattr("app.hoh_service.twilio_client.send_text", lambda *args, **kwargs: sent.append(kwargs))

    payload = {"From": "+972500000002", "ListItemTitle": "Option A"}

    asyncio.run(service.handle_whatsapp_webhook(payload, org_id=1))

    assert sent
    assert not service.messages.logged


def test_handle_webhook_falls_back_to_recent_non_open(monkeypatch):
    service = HOHService()

    recent_conversation = {
        "conversation_id": 8,
        "event_id": None,
        "pending_data_fields": {"pending_event_id": 77},
    }

    class RecentOnlyConversations(DummyConversations):
        def get_recent_open_for_contact(self, **_):
            return None

        def get_most_recent_for_contact(self, **_):
            return recent_conversation

    service.contacts = DummyContacts()
    service.events = DummyEvents()
    service.conversations = RecentOnlyConversations(recent_conversation)
    service.messages = DummyMessages()

    sent = []
    monkeypatch.setattr("app.hoh_service.twilio_client.send_text", lambda *args, **kwargs: sent.append(kwargs))

    payload = {"From": "+972500000003", "ListItemTitle": "Option B"}

    asyncio.run(service.handle_whatsapp_webhook(payload, org_id=1))

    assert not sent
    assert service.messages.logged
    assert service.messages.logged[0]["event_id"] == 77
