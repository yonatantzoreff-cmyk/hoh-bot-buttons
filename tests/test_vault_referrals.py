import pytest

from app.utils import vault


def _make_ws(rows):
    class FakeWorksheet:
        def get_all_values(self):
            return rows

    return FakeWorksheet()


def test_latest_referral_event_for_phone_returns_most_recent(monkeypatch):
    rows = [
        ["org_key", "from_phone", "to_phone", "event_id", "timestamp"],
        ["org-a", "whatsapp:+972500000001", "whatsapp:+972500000010", "EVT-10010", "2024-01-01"],
        ["org-b", "whatsapp:+972500000002", "whatsapp:+972500000010", "EVT-10020", "2024-01-02"],
        ["org-c", "whatsapp:+972500000003", "whatsapp:+972500000099", "EVT-10030", "2024-01-03"],
    ]

    ws = _make_ws(rows)
    monkeypatch.setattr(vault, "_open_ws", lambda name: ws)

    assert vault.latest_referral_event_for_phone("whatsapp:+972500000010") == "EVT-10020"
    assert vault.latest_referral_event_for_phone("+972500000099") == "EVT-10030"
    assert vault.latest_referral_event_for_phone("0500000099") == "EVT-10030"
    assert vault.latest_referral_event_for_phone("whatsapp:+972599999999") is None

