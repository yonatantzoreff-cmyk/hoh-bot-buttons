"""Tests for SHIFT_REMINDER event_id assignment."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from app.services.scheduler_job_builder import build_or_update_jobs_for_shifts


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.EmployeeRepository")
def test_shift_reminder_includes_event_id(
    mock_employee_repo,
    mock_settings_repo,
    mock_scheduled_repo,
    mock_shift_repo
):
    """Test that SHIFT_REMINDER jobs are created with event_id."""
    org_id = 1
    event_id = 42
    
    # Setup mock settings
    mock_settings_instance = Mock()
    mock_settings = {
        "enabled_global": True,
        "enabled_shift": True,
        "shift_days_before": 1,
        "shift_send_time": "12:00"
    }
    mock_settings_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_instance
    
    # Setup mock shifts (with event_id)
    future_time = datetime.utcnow() + timedelta(days=3)
    mock_shifts = [
        {
            "shift_id": 100,
            "event_id": event_id,  # Shifts have event_id
            "employee_id": 1,
            "call_time": future_time
        }
    ]
    mock_shift_instance = Mock()
    mock_shift_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shift_repo.return_value = mock_shift_instance
    
    # Setup mock employee with valid phone
    mock_employee_instance = Mock()
    mock_employee_instance.get_employee_by_id.return_value = {
        "employee_id": 1,
        "phone": "+972501234567"
    }
    mock_employee_repo.return_value = mock_employee_instance
    
    # Setup mock scheduled repo
    mock_scheduled_instance = Mock()
    mock_scheduled_instance.find_job_for_shift.return_value = None  # No existing job
    mock_scheduled_instance.create_scheduled_message.return_value = 123  # Return numeric job_id
    mock_scheduled_repo.return_value = mock_scheduled_instance
    
    # Call the function
    result = build_or_update_jobs_for_shifts(org_id, event_id)
    
    # Verify results
    assert result["created"] == 1
    assert result["blocked"] == 0
    assert result["disabled"] is False
    
    # Verify create_scheduled_message was called with event_id
    mock_scheduled_instance.create_scheduled_message.assert_called_once()
    call_kwargs = mock_scheduled_instance.create_scheduled_message.call_args[1]
    
    # Critical assertion: event_id must be set
    assert "event_id" in call_kwargs
    assert call_kwargs["event_id"] == event_id
    assert call_kwargs["shift_id"] == 100
    assert call_kwargs["message_type"] == "SHIFT_REMINDER"


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.EmployeeRepository")
def test_shift_reminder_skips_if_event_id_none(
    mock_employee_repo,
    mock_settings_repo,
    mock_scheduled_repo,
    mock_shift_repo
):
    """Test that SHIFT_REMINDER creation is skipped if event_id is None (safety check)."""
    org_id = 1
    event_id = None  # Simulating None event_id (shouldn't happen, but defensive)
    
    # Setup mock settings
    mock_settings_instance = Mock()
    mock_settings = {
        "enabled_global": True,
        "enabled_shift": True,
        "shift_days_before": 1,
        "shift_send_time": "12:00"
    }
    mock_settings_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_instance
    
    # Setup mock shifts
    future_time = datetime.utcnow() + timedelta(days=3)
    mock_shifts = [
        {
            "shift_id": 100,
            "event_id": event_id,
            "employee_id": 1,
            "call_time": future_time
        }
    ]
    mock_shift_instance = Mock()
    mock_shift_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shift_repo.return_value = mock_shift_instance
    
    # Setup mock employee
    mock_employee_instance = Mock()
    mock_employee_instance.get_employee_by_id.return_value = {
        "employee_id": 1,
        "phone": "+972501234567"
    }
    mock_employee_repo.return_value = mock_employee_instance
    
    # Setup mock scheduled repo
    mock_scheduled_instance = Mock()
    mock_scheduled_instance.find_job_for_shift.return_value = None
    mock_scheduled_repo.return_value = mock_scheduled_instance
    
    # Call the function with event_id=None
    result = build_or_update_jobs_for_shifts(org_id, event_id)
    
    # Verify that no job was created (skipped due to None event_id)
    assert result["created"] == 0
    assert result["blocked"] == 0
    
    # Verify create_scheduled_message was NOT called
    mock_scheduled_instance.create_scheduled_message.assert_not_called()
