import json

from app.services.calendar_import_service import CalendarImportService


def test_list_staging_events_parses_json_strings(monkeypatch):
    service = CalendarImportService()
    monkeypatch.setattr(service, "_ensure_staging_table", lambda: None)
    monkeypatch.setattr(
        service.staging_repo,
        "list_all",
        lambda org_id: [
            {
                "errors_json": json.dumps(["Missing date", {"field": "show_time"}]),
                "warnings_json": json.dumps(["Optional warning"]),
            }
        ],
    )

    events = service.list_staging_events(org_id=1)

    assert events[0]["errors"] == ["Missing date", {"field": "show_time"}]
    assert events[0]["warnings"] == ["Optional warning"]


def test_list_staging_events_accepts_predecoded_values(monkeypatch):
    service = CalendarImportService()
    monkeypatch.setattr(service, "_ensure_staging_table", lambda: None)
    monkeypatch.setattr(
        service.staging_repo,
        "list_all",
        lambda org_id: [
            {
                "errors_json": ["Already parsed"],
                "warnings_json": {"items": ["Warning A"]},
            }
        ],
    )

    events = service.list_staging_events(org_id=1)

    assert events[0]["errors"] == ["Already parsed"]
    assert events[0]["warnings"] == {"items": ["Warning A"]}
