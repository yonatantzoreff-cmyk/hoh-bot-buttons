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
    _generate_job_key,
)
from app.time_utils import parse_local_time_to_utc, utc_to_local_datetime


def test_generate_job_key():
    """Test job_key generation is consistent format."""
    job_key = _generate_job_key(org_id=1, entity_type="event", entity_id=100, message_type="INIT")
    assert job_key.startswith("org_1_event_100_INIT_")
    assert len(job_key) > 20  # Has UUID suffix


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


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_creates_init_and_tech(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo, mock_shifts_repo
):
    """Test that build_or_update_jobs_for_event creates TECH_REMINDER when load_in_time is set."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    load_in_time = datetime(2024, 7, 18, 18, 0)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
        "load_in_time": load_in_time,  # Has load_in_time → TECH_REMINDER created, INIT skipped
    }
    
    mock_producer = {"contact_id": 100, "phone": "+972501234567"}
    mock_technical = {"contact_id": 200, "phone": "+972509876543"}
    
    # Mock at least one shift so TECH_REMINDER is not blocked
    mock_shifts = [{"shift_id": 1, "employee_id": 1}]
    
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
    
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify INIT is skipped (has load_in_time) and TECH_REMINDER is created
    assert result["init_status"] == "skipped"
    assert result["init_skip_reason"] == "has_load_in_time"
    assert "tech_job_id" in result
    assert result["tech_status"] == "created"
    
    # Verify create_scheduled_message was called once for TECH_REMINDER
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 1
    
    # Check TECH_REMINDER job creation
    tech_call = mock_scheduled_repo_instance.create_scheduled_message.call_args
    assert tech_call[1]["message_type"] == "TECH_REMINDER"
    assert tech_call[1]["event_id"] == 1


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_blocks_when_phone_missing(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo, mock_shifts_repo
):
    """Test that jobs are blocked when required phone is missing."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    load_in_time = datetime(2024, 7, 18, 18, 0)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": None,  # No technical contact
        "load_in_time": load_in_time,  # Has load_in_time → TECH_REMINDER should be created but blocked
    }
    
    mock_producer = {"contact_id": 100, "phone": None}  # No phone
    
    # Mock at least one shift so TECH_REMINDER is attempted (but will be blocked due to no phone)
    mock_shifts = [{"shift_id": 1, "employee_id": 1}]
    
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
    
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify INIT is skipped (has load_in_time) and TECH_REMINDER is blocked (no phone)
    assert result["init_status"] == "skipped"
    assert result["init_skip_reason"] == "has_load_in_time"
    assert result["tech_status"] == "blocked"
    
    # Verify status was updated to blocked for TECH_REMINDER
    assert mock_scheduled_repo_instance.update_status.call_count == 1


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_updates_existing_not_sent(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo, mock_shifts_repo
):
    """Test that existing jobs not yet sent are updated with new send_at."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    load_in_time = datetime(2024, 7, 18, 18, 0)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
        "load_in_time": load_in_time,  # Has load_in_time → Only TECH_REMINDER is relevant
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
    
    # Existing TECH_REMINDER job (scheduled, not sent)
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
    mock_scheduled_repo_instance.find_job_for_event.return_value = mock_tech_job
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Mock at least one shift so TECH_REMINDER is updated
    mock_shifts = [{"shift_id": 1, "employee_id": 1}]
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify INIT is skipped (has load_in_time) and TECH_REMINDER is updated
    assert result["init_status"] == "skipped"
    assert result["init_skip_reason"] == "has_load_in_time"
    assert result["tech_status"] == "updated"
    
    # Verify update_send_at was called for TECH_REMINDER job
    assert mock_scheduled_repo_instance.update_send_at.call_count == 1
    
    # Verify no new jobs were created
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 0


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_skips_already_sent(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo, mock_shifts_repo
):
    """Test that jobs already sent are not updated."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    load_in_time = datetime(2024, 7, 18, 18, 0)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
        "load_in_time": load_in_time,  # Has load_in_time → Only TECH_REMINDER is relevant
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
    
    # Existing TECH_REMINDER job (already sent)
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
    mock_scheduled_repo_instance.find_job_for_event.return_value = mock_tech_job
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Mock at least one shift so TECH_REMINDER is checked
    mock_shifts = [{"shift_id": 1, "employee_id": 1}]
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify INIT is skipped (has load_in_time) and TECH_REMINDER is skipped (already sent)
    assert result["init_status"] == "skipped"
    assert result["init_skip_reason"] == "has_load_in_time"
    assert result["tech_status"] == "skipped"
    assert result["tech_skip_reason"] == "already_sent_or_failed"
    
    # Verify no updates were made
    assert mock_scheduled_repo_instance.update_send_at.call_count == 0
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 0


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_for_event_skips_tech_when_no_shifts(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo, mock_shifts_repo
):
    """Test that TECH_REMINDER job is blocked when event has load_in_time but no shifts yet."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    load_in_time = datetime(2024, 7, 18, 18, 0)  # Has load_in_time
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
        "load_in_time": load_in_time,  # Has load_in_time, so TECH_REMINDER should be created
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
    
    # Mock NO shifts - event has no shifts yet
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = []
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify INIT job is skipped (has load_in_time) but TECH_REMINDER is created and blocked
    assert result["init_status"] == "skipped"
    assert result["init_skip_reason"] == "has_load_in_time"
    assert result["tech_status"] == "blocked"  # Should be blocked due to no shifts
    assert "tech_job_id" in result  # Job should be created
    
    # Verify create_scheduled_message was called once for TECH_REMINDER
    assert mock_scheduled_repo_instance.create_scheduled_message.call_count == 1
    
    # Check TECH_REMINDER job creation
    tech_call = mock_scheduled_repo_instance.create_scheduled_message.call_args
    assert tech_call[1]["message_type"] == "TECH_REMINDER"
    assert tech_call[1]["event_id"] == 1


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


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_unblocks_tech_when_technical_contact_added(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo, mock_shifts_repo
):
    """Test that TECH_REMINDER job unblocks when technical contact with phone is added."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    load_in_time = datetime(2024, 7, 18, 18, 0)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,  # Technical contact NOW assigned
        "load_in_time": load_in_time,
    }
    
    mock_producer = {"contact_id": 100, "phone": None}  # Producer has no phone
    mock_technical = {"contact_id": 200, "phone": "+972509876543"}  # Technical has phone!
    
    mock_settings = {
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Existing TECH_REMINDER job (blocked due to missing phone)
    mock_tech_job = {
        "job_id": "job_tech_1", 
        "status": "blocked",
        "last_error": "Missing recipient phone"
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
    mock_scheduled_repo_instance.find_job_for_event.return_value = mock_tech_job
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Mock at least one shift
    mock_shifts = [{"shift_id": 1, "employee_id": 1}]
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify TECH_REMINDER job is unblocked (technical contact added with phone)
    assert result["tech_status"] == "updated"
    
    # Verify update_status was called to unblock the job (2 calls: 1 for INIT skip, 1 for TECH unblock)
    assert mock_scheduled_repo_instance.update_status.call_count == 2
    # Check the second call (for TECH_REMINDER unblocking)
    tech_call = mock_scheduled_repo_instance.update_status.call_args_list[1]
    assert tech_call[0][0] == "job_tech_1"
    assert tech_call[1]["status"] == "scheduled"
    assert tech_call[1]["last_error"] is None


@patch("app.services.scheduler_job_builder.EmployeeShiftRepository")
@patch("app.services.scheduler_job_builder.EventRepository")
@patch("app.services.scheduler_job_builder.ScheduledMessageRepository")
@patch("app.services.scheduler_job_builder.SchedulerSettingsRepository")
@patch("app.services.scheduler_job_builder.ContactRepository")
def test_build_jobs_unblocks_tech_when_shifts_added(
    mock_contact_repo, mock_settings_repo, mock_scheduled_repo, mock_event_repo, mock_shifts_repo
):
    """Test that TECH_REMINDER job unblocks when shifts are added to event."""
    # Setup mocks
    event_date = date(2024, 7, 18)
    load_in_time = datetime(2024, 7, 18, 18, 0)
    mock_event = {
        "event_id": 1,
        "event_date": event_date,
        "producer_contact_id": 100,
        "technical_contact_id": 200,
        "load_in_time": load_in_time,
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
    
    # Existing TECH_REMINDER job (blocked due to no employees)
    mock_tech_job = {
        "job_id": "job_tech_1", 
        "status": "blocked",
        "last_error": "No employees assigned to event"
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
    mock_scheduled_repo_instance.find_job_for_event.return_value = mock_tech_job
    mock_scheduled_repo.return_value = mock_scheduled_repo_instance
    
    # Mock shifts NOW exist (were added)
    mock_shifts = [{"shift_id": 1, "employee_id": 1}]
    mock_shifts_repo_instance = Mock()
    mock_shifts_repo_instance.list_shifts_for_event.return_value = mock_shifts
    mock_shifts_repo.return_value = mock_shifts_repo_instance
    
    # Run the function
    result = build_or_update_jobs_for_event(org_id=1, event_id=1)
    
    # Verify TECH_REMINDER job is unblocked (shifts added)
    assert result["tech_status"] == "updated"
    
    # Verify update_status was called to unblock the job (2 calls: 1 for INIT skip, 1 for TECH unblock)
    assert mock_scheduled_repo_instance.update_status.call_count == 2
    # Check the second call (for TECH_REMINDER unblocking)
    tech_call = mock_scheduled_repo_instance.update_status.call_args_list[1]
    assert tech_call[0][0] == "job_tech_1"
    assert tech_call[1]["status"] == "scheduled"
    assert tech_call[1]["last_error"] is None
