import os

import pytest

os.environ.setdefault("TWILIO_ACCOUNT_SID", "test-sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-token")

from app.routers import webhook


def _stub_find_col_index(headers, wanted):
    lower_headers = [h.lower() for h in headers]
    for alias in wanted:
        try:
            return lower_headers.index(alias.lower())
        except ValueError:
            continue
    return None


@pytest.mark.anyio
async def test_resolve_event_id_prefers_contact_related_status(monkeypatch):
    headers = ["event_id", "supplier_phone", "status"]
    values = [
        headers,
        ["EVT-10010", "+972511111112", "waiting_load_in"],
        ["EVT-10040", "0503001613", "waiting_load_in"],
        ["EVT-10030", "0503001613", "contact_required"],
    ]

    class FakeWorksheet:
        def row_values(self, row_number):
            return values[row_number - 1]

        def get_all_values(self):
            return values

    class FakeSpreadsheet:
        def __init__(self, worksheet):
            self.worksheet = worksheet

    ws = FakeWorksheet()
    ss = FakeSpreadsheet(ws)

    monkeypatch.setattr(webhook.sheets, "open_sheet", lambda: ss)
    monkeypatch.setattr(webhook.sheets, "get_worksheet", lambda _ss, _name: ws)
    monkeypatch.setattr(webhook.sheets, "get_headers", lambda _ws: headers)
    monkeypatch.setattr(webhook.sheets, "find_col_index", _stub_find_col_index)

    assert webhook._resolve_event_id_for_phone("whatsapp:+972503001613") == "EVT-10030"
    assert webhook._resolve_event_id_for_phone("whatsapp:+0503001613") == "EVT-10030"


@pytest.mark.anyio
async def test_resolve_event_id_prefers_latest_referral(monkeypatch):
    headers = ["event_id", "supplier_phone", "status"]
    values = [
        headers,
        ["EVT-10010", "+972503001613", "contact_required"],
        ["EVT-10020", "+972503001613", "contact_required"],
    ]

    class FakeWorksheet:
        def row_values(self, row_number):
            return values[row_number - 1]

        def get_all_values(self):
            return values

    class FakeSpreadsheet:
        def __init__(self, worksheet):
            self.worksheet = worksheet

    ws = FakeWorksheet()
    ss = FakeSpreadsheet(ws)

    monkeypatch.setattr(webhook.sheets, "open_sheet", lambda: ss)
    monkeypatch.setattr(webhook.sheets, "get_worksheet", lambda _ss, _name: ws)
    monkeypatch.setattr(webhook.sheets, "get_headers", lambda _ws: headers)
    monkeypatch.setattr(webhook.sheets, "find_col_index", _stub_find_col_index)

    # Latest referral should short-circuit sheet scan
    monkeypatch.setattr(webhook.vault, "latest_referral_event_for_phone", lambda phone: "EVT-99999")

    assert webhook._resolve_event_id_for_phone("whatsapp:+972503001613") == "EVT-99999"
