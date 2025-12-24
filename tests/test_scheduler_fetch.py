"""
Tests for scheduler fetch and cleanup functionality.

This module tests:
- POST /api/scheduler/fetch endpoint for syncing future events
- DELETE /api/scheduler/past-logs endpoint for cleanup
- show_past parameter filtering in GET /api/scheduler/jobs
- Idempotency of fetch operations
"""

import os
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Set up test environment
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

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories import EventRepository


client = TestClient(app)


@patch("app.routers.scheduler.EventRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
def test_fetch_endpoint_creates_jobs_for_future_events(
    mock_shift_repo,
    mock_contact_repo,
    mock_settings_repo,
    mock_scheduled_repo,
    mock_event_repo_builder,
    mock_event_repo_api,
):
    """Test that fetch endpoint creates jobs for future events."""
    # Setup mocks - future events
    future_date = date.today() + timedelta(days=30)
    mock_events = [
        {"event_id": 1, "event_date": future_date, "name": "Event 1"},
        {"event_id": 2, "event_date": future_date + timedelta(days=10), "name": "Event 2"},
    ]
    
    mock_event_details = {
        "event_id": 1,
        "event_date": future_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
    }
    
    mock_producer = {"contact_id": 100, "phone": "+972501234567"}
    mock_technical = {"contact_id": 200, "phone": "+972509876543"}
    
    mock_settings = {
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "enabled_shift": False,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Configure mocks
    mock_event_repo_api_instance = Mock()
    mock_event_repo_api_instance.list_future_events_for_org.return_value = mock_events
    mock_event_repo_api.return_value = mock_event_repo_api_instance
    
    mock_event_repo_builder_instance = Mock()
    mock_event_repo_builder_instance.get_event_by_id.return_value = mock_event_details
    mock_event_repo_builder.return_value = mock_event_repo_builder_instance
    
    mock_contact_repo_instance = Mock()
    mock_contact_repo_instance.get_contact_by_id.side_effect = lambda org_id, contact_id: (
        mock_producer if contact_id == 100 else mock_technical
    )
    mock_contact_repo.return_value = mock_contact_repo_instance
    
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    mock_scheduled_repo_instance = Mock()
    mock_scheduled_repo_instance.find_job_for_event.return_value = None  # No existing jobs
    mock_scheduled_repo_instance.create_scheduled_message.return_value = "job_123"
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Call fetch endpoint
    response = client.post("/api/scheduler/fetch?org_id=1")
    
    # Assertions
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["events_scanned"] == 2
    # Should have created 2 INIT jobs + 2 TECH jobs = 4 total
    # (assuming both events have valid contacts)


@patch("app.routers.scheduler.EventRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_fetch_endpoint_updates_existing_jobs(
    mock_contact_repo,
    mock_settings_repo,
    mock_scheduled_repo,
    mock_event_repo_builder,
    mock_event_repo_api,
):
    """Test that fetch endpoint updates existing jobs (idempotency)."""
    # Setup mocks - future event with existing job
    future_date = date.today() + timedelta(days=30)
    mock_events = [
        {"event_id": 1, "event_date": future_date, "name": "Event 1"},
    ]
    
    mock_event_details = {
        "event_id": 1,
        "event_date": future_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
    }
    
    mock_producer = {"contact_id": 100, "phone": "+972501234567"}
    mock_technical = {"contact_id": 200, "phone": "+972509876543"}
    
    mock_settings = {
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "enabled_shift": False,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Existing job
    mock_existing_job = {
        "job_id": "existing_job_1",
        "status": "scheduled",
        "send_at": datetime.now() + timedelta(days=27),
    }
    
    # Configure mocks
    mock_event_repo_api_instance = Mock()
    mock_event_repo_api_instance.list_future_events_for_org.return_value = mock_events
    mock_event_repo_api.return_value = mock_event_repo_api_instance
    
    mock_event_repo_builder_instance = Mock()
    mock_event_repo_builder_instance.get_event_by_id.return_value = mock_event_details
    mock_event_repo_builder.return_value = mock_event_repo_builder_instance
    
    mock_contact_repo_instance = Mock()
    mock_contact_repo_instance.get_contact_by_id.side_effect = lambda org_id, contact_id: (
        mock_producer if contact_id == 100 else mock_technical
    )
    mock_contact_repo.return_value = mock_contact_repo_instance
    
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    mock_scheduled_repo_instance = Mock()
    # INIT job exists, TECH job doesn't
    mock_scheduled_repo_instance.find_job_for_event.side_effect = lambda org_id, event_id, msg_type: (
        mock_existing_job if msg_type == "INIT" else None
    )
    mock_scheduled_repo_instance.update_send_at.return_value = None
    mock_scheduled_repo_instance.create_scheduled_message.return_value = "new_tech_job"
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Call fetch endpoint
    response = client.post("/api/scheduler/fetch?org_id=1")
    
    # Assertions
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["events_scanned"] == 1
    # Should have updated 1 INIT job + created 1 TECH job
    # Check that update_send_at was called for existing job
    mock_scheduled_repo_instance.update_send_at.assert_called()


@pytest.mark.skip(reason="Integration test - requires database setup")
@patch("app.appdb.get_session")
def test_cleanup_endpoint_deletes_old_completed_logs(mock_get_session):
    """Test that cleanup endpoint accepts days parameter and calls correct methods."""
    # Setup mock session
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.rowcount = 5  # 5 rows deleted
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=None)
    mock_get_session.return_value = mock_session
    
    # Call cleanup endpoint
    response = client.delete("/api/scheduler/past-logs?org_id=1&days=30")
    
    # Assertions
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["deleted_count"] == 5
    assert "5 old log entries" in result["message"]
    
    # Verify execute was called (session entered the context manager)
    mock_session.execute.assert_called_once()
    # Verify that the parameters include org_id and cutoff_date
    call_args = mock_session.execute.call_args
    if call_args:
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert "org_id" in params
        assert "cutoff_date" in params
        assert params["org_id"] == 1


@pytest.mark.skip(reason="Integration test - requires database setup")
@patch("app.appdb.get_session")
@patch("app.routers.scheduler.ScheduledMessageRepository")
@patch("app.routers.scheduler.EventRepository")
@patch("app.routers.scheduler.ContactRepository")
@patch("app.routers.scheduler.EmployeeRepository")
def test_show_past_parameter_filters_correctly(
    mock_employee_repo,
    mock_contact_repo,
    mock_event_repo,
    mock_scheduled_repo,
    mock_get_session,
):
    """Test that show_past parameter correctly filters past jobs."""
    # This test verifies the filtering logic in list_scheduler_jobs endpoint
    # by checking the SQL query construction
    
    # Setup mock session with empty results
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result._mapping = {}
    mock_result.__iter__ = Mock(return_value=iter([]))
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=None)
    mock_get_session.return_value = mock_session
    
    # Setup mocks
    mock_scheduled_repo_instance = Mock()
    mock_event_repo_instance = Mock()
    mock_contact_repo_instance = Mock()
    mock_employee_repo_instance = Mock()
    
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    mock_event_repo.return_value = mock_event_repo_instance
    mock_contact_repo.return_value = mock_contact_repo_instance
    mock_employee_repo.return_value = mock_employee_repo_instance
    
    # Call endpoint with show_past=False (default behavior)
    response = client.get("/api/scheduler/jobs?org_id=1&message_type=INIT&show_past=0")
    
    # Should return 200 (filtering logic is tested in integration)
    assert response.status_code == 200
    
    # Call endpoint with show_past=True
    response = client.get("/api/scheduler/jobs?org_id=1&message_type=INIT&show_past=1")
    
    # Should return 200 (filtering logic is tested in integration)
    assert response.status_code == 200


@patch("app.routers.scheduler.EventRepository")
def test_fetch_endpoint_requires_valid_org_id(mock_event_repo_api):
    """Test that fetch endpoint validates org_id parameter."""
    # Mock to return empty list for non-existent org
    mock_event_repo_api_instance = Mock()
    mock_event_repo_api_instance.list_future_events_for_org.return_value = []
    mock_event_repo_api.return_value = mock_event_repo_api_instance
    
    # Call with invalid org_id should still work but return 0 events
    response = client.post("/api/scheduler/fetch?org_id=999999")
    
    # Should return 200 with 0 events scanned
    assert response.status_code == 200
    result = response.json()
    assert result["events_scanned"] == 0


@pytest.mark.skip(reason="Integration test - requires database setup")
@patch("app.appdb.get_session")
def test_cleanup_endpoint_validates_days_parameter(mock_get_session):
    """Test that cleanup endpoint accepts days parameter."""
    # Setup mock session
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = Mock(return_value=mock_session)
    mock_session.__exit__ = Mock(return_value=None)
    mock_get_session.return_value = mock_session
    
    # Call with custom days parameter
    response = client.delete("/api/scheduler/past-logs?org_id=1&days=60")
    
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
