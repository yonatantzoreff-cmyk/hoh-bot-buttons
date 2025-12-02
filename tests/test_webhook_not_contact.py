import os
import pytest

os.environ.setdefault("TWILIO_ACCOUNT_SID", "test-sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-token")

from app.routers import webhook


class _FormRequest:
    def __init__(self, form_data: dict):
        self._form_data = form_data

    async def form(self):
        return self._form_data


@pytest.mark.anyio
async def test_not_contact_uses_payload_event_id(monkeypatch):
    sent_prompts: list[tuple[str, str]] = []
    status_updates: list[tuple[str, str]] = []

    def fake_send_contact(to_number: str, event_id: str, variables=None):
        sent_prompts.append((to_number, event_id))

    def fake_update_status(event_id: str, status: str):
        status_updates.append((event_id, status))
        return True

    def fail_resolve(_from: str):
        raise AssertionError("event lookup by phone should not be used")

    monkeypatch.setattr(webhook, "_send_contact", fake_send_contact)
    monkeypatch.setattr(webhook, "_update_status_by_event", fake_update_status)
    monkeypatch.setattr(webhook, "_resolve_event_id_for_phone", fail_resolve)
    monkeypatch.setattr(webhook, "_append_log", lambda *args, **kwargs: None)

    for event_id in ("EVT-AAA", "EVT-BBB"):
        response = await webhook.whatsapp_webhook(
            _FormRequest(
                {
                    "MessageType": "button",
                    "ButtonPayload": f"NOT_CONTACT_{event_id}",
                    "From": "whatsapp:+15551234567",
                    "To": "whatsapp:+972555000111",
                }
            )
        )
        assert response.status_code == 200

    assert sent_prompts == [
        ("whatsapp:+15551234567", "EVT-AAA"),
        ("whatsapp:+15551234567", "EVT-BBB"),
    ]
    assert status_updates == [
        ("EVT-AAA", "contact_required"),
        ("EVT-BBB", "contact_required"),
    ]
