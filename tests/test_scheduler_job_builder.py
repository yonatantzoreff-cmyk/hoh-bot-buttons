"""
Tests for scheduler job builder service.

This module tests the build_or_update_jobs_for_event and build_or_update_jobs_for_shifts
functions which create and update scheduled message jobs.
"""

import os
from datetime import date, datetime, time, timedelta
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

from app.services.scheduler_job_builder import (
    build_or_update_jobs_for_event,
    build_or_update_jobs_for_shifts,
    _validate_phone,
    _generate_job_id,
)
from app.time_utils import parse_local_time_to_utc, utc_to_local_datetime


def test_generate_job_id():
    """Test job_id generation is consistent format."""
    job_id = _generate_job_id(org_id=1, entity_type="event", entity_id=100, message_type="INIT")
    assert job_id.startswith("org_1_event_100_INIT_")
    assert len(job_id) > 20  # Has UUID suffix


def test_validate_phone_valid():
    """Test phone validation with valid phone number."""
    is_valid, normalized = _validate_phone("+972501234567")
    assert is_valid is True
    assert normalized is not None


def test_validate_phone_invalid():
    """Test phone validation with invalid phone number."""
    is_valid, normalized = _validate_phone("123")
    assert is_valid is False
    assert normalized is None


def test_validate_phone_none():
    """Test phone validation with None."""
    is_valid, normalized = _validate_phone(None)
    assert is_valid is False
    assert normalized is None


@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_creates_init_and_tech(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo
):
    """Test that build_or_update_jobs_for_event creates INIT and TECH_REMINDER jobs."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
    }
    
    mock_producer = {"contact_id": 100, "phone": "+972501234567"}
    mock_technical = {"contact_id": 200, "phone": "+972509876543"}
    
    mock_settings = {
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Configure mocks
    mock_event_repo_instance = Mock()
    mock_event_repo_instance.get_event_by_id.return_value = mock_event
    mock_event_repo.return_value = mock_event_repo_instance
    
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
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify
    assert "init_job_id" in result
    assert "tech_job_id" in result
    assert result["init_status"] == "created"
    assert result["tech_status"] == "created"
    
    # Verify create_scheduled_message was called twice (once for INIT, once for TECH_REMINDER)
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 2
    
    # Check INIT job creation
    init_call = mock_scheduled_repo_instance.create_scheduled_message.call_args_list[0]
    assert init_call[1]["message_type"] == "INIT"
    assert init_call[1]["event_id"] == 1
    
    # Check TECH_REMINDER job creation
    tech_call = mock_scheduled_repo_instance.create_scheduled_message.call_args_list[1]
    assert tech_call[1]["message_type"] == "TECH_REMINDER"
    assert tech_call[1]["event_id"] == 1


@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_blocks_when_phone_missing(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo
):
    """Test that jobs are blocked when required phone is missing."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": None,  # No technical contact
    }
    
    mock_producer = {"contact_id": 100, "phone": None}  # No phone
    
    mock_settings = {
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Configure mocks
    mock_event_repo_instance = Mock()
    mock_event_repo_instance.get_event_by_id.return_value = mock_event
    mock_event_repo.return_value = mock_event_repo_instance
    
    mock_contact_repo_instance = Mock()
    mock_contact_repo_instance.get_contact_by_id.return_value = mock_producer
    mock_contact_repo.return_value = mock_contact_repo_instance
    
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    mock_scheduled_repo_instance = Mock()
    mock_scheduled_repo_instance.find_job_for_event.return_value = None
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify both jobs are blocked
    assert result["init_status"] == "blocked"
    assert result["tech_status"] == "blocked"
    
    # Verify status was updated to blocked
    assert mock_scheduled_repo_instance.update_status.call_count == 2


@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_updates_existing_not_sent(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo
):
    """Test that existing jobs not yet sent are updated with new send_at."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
    }
    
    mock_producer = {"contact_id": 100, "phone": "+972501234567"}
    mock_technical = {"contact_id": 200, "phone": "+972509876543"}
    
    mock_settings = {
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Existing jobs (scheduled, not sent)
    mock_init_job = {"job_id": "job_init_1", "status": "scheduled"}
    mock_tech_job = {"job_id": "job_tech_1", "status": "scheduled"}
    
    # Configure mocks
    mock_event_repo_instance = Mock()
    mock_event_repo_instance.get_event_by_id.return_value = mock_event
    mock_event_repo.return_value = mock_event_repo_instance
    
    mock_contact_repo_instance = Mock()
    mock_contact_repo_instance.get_contact_by_id.side_effect = lambda org_id, contact_id: (
        mock_producer if contact_id == 100 else mock_technical
    )
    mock_contact_repo.return_value = mock_contact_repo_instance
    
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    mock_scheduled_repo_instance = Mock()
    mock_scheduled_repo_instance.find_job_for_event.side_effect = lambda org_id, event_id, msg_type: (
        mock_init_job if msg_type == "INIT" else mock_tech_job
    )
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify
    assert result["init_status"] == "updated"
    assert result["tech_status"] == "updated"
    
    # Verify update_send_at was called for both jobs
    assert mock_scheduled_repo_instance.update_send_at.call_count == 2
    
    # Verify no new jobs were created
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 0


@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_skips_already_sent(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo
):
    """Test that jobs already sent are not updated."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
    }
    
    mock_producer = {"contact_id": 100, "phone": "+972501234567"}
    mock_technical = {"contact_id": 200, "phone": "+972509876543"}
    
    mock_settings = {
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Existing jobs (already sent)
    mock_init_job = {"job_id": "job_init_1", "status": "sent"}
    mock_tech_job = {"job_id": "job_tech_1", "status": "sent"}
    
    # Configure mocks
    mock_event_repo_instance = Mock()
    mock_event_repo_instance.get_event_by_id.return_value = mock_event
    mock_event_repo.return_value = mock_event_repo_instance
    
    mock_contact_repo_instance = Mock()
    mock_contact_repo_instance.get_contact_by_id.side_effect = lambda org_id, contact_id: (
        mock_producer if contact_id == 100 else mock_technical
    )
    mock_contact_repo.return_value = mock_contact_repo_instance
    
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    mock_scheduled_repo_instance = Mock()
    mock_scheduled_repo_instance.find_job_for_event.side_effect = lambda org_id, event_id, msg_type: (
        mock_init_job if msg_type == "INIT" else mock_tech_job
    )
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify
    assert result["init_status"] == "already_sent_or_failed"
    assert result["tech_status"] == "already_sent_or_failed"
    
    # Verify no updates were made
    assert mock_scheduled_repo_instance.update_send_at.call_count == 0
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 0


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.EmployeeRepository")
def test_build_jobs_for_shifts_creates_shift_reminders(
    mock_employee_repo, mock_settings_repo, mock_scheduled_repo, mock_shifts_repo
):
    """Test that build_or_update_jobs_for_shifts creates SHIFT_REMINDER jobs."""
    # Setup mocks
    call_time = parse_local_time_to_utc(date(2024, 7, 18), "14:00")
    mock_shifts = [
        {
            "shift_id": 1,
            "employee_id": 10,
            "call_time": call_time,
        },
        {
            "shift_id": 2,
            "employee_id": 20,
            "call_time": call_time,
        },
    ]
    
    mock_employee1 = {"employee_id": 10, "phone": "+972501234567"}
    mock_employee2 = {"employee_id": 20, "phone": "+972509876543"}
    
    mock_settings = {
        "enabled_global": True,
        "enabled_shift": True,
        "shift_days_before": 1,
        "shift_send_time": "12:00",
    }
    
    # Configure mocks
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    mock_employee_repo_instance = Mock()
    mock_employee_repo_instance.get_employee_by_id.side_effect = lambda org_id, employee_id: (
        mock_employee1 if employee_id == 10 else mock_employee2
    )
    mock_employee_repo.return_value = mock_employee_repo_instance
    
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    mock_scheduled_repo_instance = Mock()
    mock_scheduled_repo_instance.find_job_for_shift.return_value = None
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_shifts(org_id=1, event_id=1)
    
    # Verify
    assert result["processed_count"] == 2
    assert result["created"] == 2
    assert result["blocked"] == 0
    
    # Verify create_scheduled_message was called twice
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 2


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.EmployeeRepository")
def test_build_jobs_for_shifts_blocks_when_employee_phone_missing(
    mock_employee_repo, mock_settings_repo, mock_scheduled_repo, mock_shifts_repo
):
    """Test that shift reminder jobs are blocked when employee phone is missing."""
    # Setup mocks
    call_time = parse_local_time_to_utc(date(2024, 7, 18), "14:00")
    mock_shifts = [
        {
            "shift_id": 1,
            "employee_id": 10,
            "call_time": call_time,
        },
    ]
    
    mock_employee = {"employee_id": 10, "phone": None}  # No phone
    
    mock_settings = {
        "enabled_global": True,
        "enabled_shift": True,
        "shift_days_before": 1,
        "shift_send_time": "12:00",
    }
    
    # Configure mocks
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    mock_employee_repo_instance = Mock()
    mock_employee_repo_instance.get_employee_by_id.return_value = mock_employee
    mock_employee_repo.return_value = mock_employee_repo_instance
    
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    mock_scheduled_repo_instance = Mock()
    mock_scheduled_repo_instance.find_job_for_shift.return_value = None
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_shifts(org_id=1, event_id=1)
    
    # Verify
    assert result["processed_count"] == 1
    assert result["blocked"] == 1
    assert result["created"] == 0
    
    # Verify status was updated to blocked
    assert mock_scheduled_repo_instance.update_status.call_count == 1


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.EmployeeRepository")
def test_build_jobs_for_shifts_disabled(
    mock_employee_repo, mock_settings_repo, mock_scheduled_repo, mock_shifts_repo
):
    """Test that build_or_update_jobs_for_shifts returns disabled when settings are off."""
    # Setup mocks
    mock_settings = {
        "enabled_global": False,  # Disabled
        "enabled_shift": True,
        "shift_days_before": 1,
        "shift_send_time": "12:00",
    }
    
    # Configure mocks
    mock_settings_repo_instance = Mock()
    mock_settings_repo_instance.get_or_create_settings.return_value = mock_settings
    mock_settings_repo.return_value = mock_settings_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_shifts(org_id=1, event_id=1)
    
    # Verify
    assert result["disabled"] is True
    assert result["processed_count"] == 0
    
    # Verify no shifts were queried
    mock_shifts_repo.return_value.list_shifts_for_event.assert_not_called()
