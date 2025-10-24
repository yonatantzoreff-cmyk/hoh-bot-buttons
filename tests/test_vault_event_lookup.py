from app.utils import vault


def test_get_event_row_by_id_returns_structured_values(monkeypatch):
    captured_ids = []

    def fake_get_event_by_id(event_id: str):
        captured_ids.append(event_id)
        return {
            "event_id": "EVT-42",
            "event_name": "מופע לדוגמה",
            "תאריך": "2024-05-17",
            "שעת מופע": "21:30",
            "load_in_time": "18:00",
        }

    monkeypatch.setattr(vault.sheets, "get_event_by_id", fake_get_event_by_id)

    row = vault.get_event_row_by_id("EVT-42")

    assert captured_ids == ["EVT-42"]
    assert row == {
        "event_id": "EVT-42",
        "event_name": "מופע לדוגמה",
        "event_date": "2024-05-17",
        "event_time": "21:30",
        "load_in_time": "18:00",
    }


def test_get_event_row_by_id_returns_none_for_missing(monkeypatch):

    monkeypatch.setattr(vault.sheets, "get_event_by_id", lambda event_id: None)

    assert vault.get_event_row_by_id("EVT-404") is None
    assert vault.get_event_row_by_id("") is None
