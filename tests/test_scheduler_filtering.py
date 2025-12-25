"""
Tests for scheduler INIT message filtering based on load_in_time.

This module tests that events with load_in_time do NOT get INIT messages.
"""

import os
from datetime import datetime, date, timedelta
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

# Set up test environment
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "test-sid")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-token")
os.environ.setdefault("CONTENT_SID_INIT", "HXINIT")

import pytest

from app.services.scheduler_job_builder import (
    build_or_update_jobs_for_event,
    SKIP_REASON_HAS_LOAD_IN_TIME,
)
from app.repositories import EventRepository, SchedulerSettingsRepository, ContactRepository


def test_init_job_skipped_when_event_has_load_in_time():
    """Test that INIT job is skipped when event has load_in_time."""
    
    # Mock event with load_in_time
    event_with_load_in = {
        "event_id": 100,
        "org_id": 1,
        "name": "Test Event",
        "event_date": date(2024, 2, 15),
        "show_time": datetime(2024, 2, 15, 20, 0, tzinfo=ZoneInfo("UTC")),
        "load_in_time": datetime(2024, 2, 15, 18, 0, tzinfo=ZoneInfo("UTC")),  # Has load-in time
        "producer_contact_id": 10,
        "technical_contact_id": 20,
    }
    
    # Mock settings
    settings = {
        "org_id": 1,
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Mock producer contact
    producer = {
        "contact_id": 10,
        "name": "Producer",
        "phone": "+972501234567"
    }
    
    # Mock technical contact
    technician = {
        "contact_id": 20,
        "name": "Technician",
        "phone": "+972509876543"
    }
    
    with patch.object(EventRepository, "get_event_by_id", return_value=event_with_load_in):
        with patch.object(SchedulerSettingsRepository, "get_or_create_settings", return_value=settings):
            with patch.object(ContactRepository, "get_contact_by_id", side_effect=lambda **kwargs: producer if kwargs.get("contact_id") == 10 else technician):
                with patch("app.services.scheduler_job_builder.ScheduledMessageRepository") as MockScheduledRepo:
                    # Mock that no existing job exists
                    mock_scheduled_repo = MockScheduledRepo.return_value
                    mock_scheduled_repo.find_job_for_event.return_value = None
                    
                    result = build_or_update_jobs_for_event(org_id=1, event_id=100)
                    
                    # INIT should be skipped due to load_in_time
                    assert result["init_status"] == "skipped"
                    assert result["init_skip_reason"] == SKIP_REASON_HAS_LOAD_IN_TIME
                    
                    # TECH_REMINDER should still be created (not affected by load_in_time)
                    assert result["tech_status"] in ("created", "blocked", "updated")


def test_init_job_created_when_event_has_no_load_in_time():
    """Test that INIT job is created when event does NOT have load_in_time."""
    
    # Mock event WITHOUT load_in_time
    event_without_load_in = {
        "event_id": 101,
        "org_id": 1,
        "name": "Test Event 2",
        "event_date": date(2024, 2, 15),
        "show_time": datetime(2024, 2, 15, 20, 0, tzinfo=ZoneInfo("UTC")),
        "load_in_time": None,  # No load-in time
        "producer_contact_id": 10,
        "technical_contact_id": 20,
    }
    
    # Mock settings
    settings = {
        "org_id": 1,
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Mock producer contact
    producer = {
        "contact_id": 10,
        "name": "Producer",
        "phone": "+972501234567"
    }
    
    # Mock technical contact
    technician = {
        "contact_id": 20,
        "name": "Technician",
        "phone": "+972509876543"
    }
    
    with patch.object(EventRepository, "get_event_by_id", return_value=event_without_load_in):
        with patch.object(SchedulerSettingsRepository, "get_or_create_settings", return_value=settings):
            with patch.object(ContactRepository, "get_contact_by_id", side_effect=lambda **kwargs: producer if kwargs.get("contact_id") == 10 else technician):
                with patch("app.services.scheduler_job_builder.ScheduledMessageRepository") as MockScheduledRepo:
                    # Mock that no existing job exists
                    mock_scheduled_repo = MockScheduledRepo.return_value
                    mock_scheduled_repo.find_job_for_event.return_value = None
                    mock_scheduled_repo.create_scheduled_message.return_value = "job-123"
                    
                    result = build_or_update_jobs_for_event(org_id=1, event_id=101)
                    
                    # INIT should be created (no load_in_time)
                    assert result["init_status"] in ("created", "blocked")
                    assert "init_skip_reason" not in result or result["init_skip_reason"] != SKIP_REASON_HAS_LOAD_IN_TIME


def test_existing_init_job_marked_skipped_when_load_in_added():
    """Test that existing INIT job is marked as skipped when load_in_time is added to event."""
    
    # Mock event with load_in_time (newly added)
    event_with_load_in = {
        "event_id": 102,
        "org_id": 1,
        "name": "Test Event 3",
        "event_date": date(2024, 2, 15),
        "show_time": datetime(2024, 2, 15, 20, 0, tzinfo=ZoneInfo("UTC")),
        "load_in_time": datetime(2024, 2, 15, 18, 0, tzinfo=ZoneInfo("UTC")),  # Newly added
        "producer_contact_id": 10,
        "technical_contact_id": 20,
    }
    
    # Mock settings
    settings = {
        "org_id": 1,
        "enabled_global": True,
        "enabled_init": True,
        "enabled_tech": True,
        "init_days_before": 28,
        "init_send_time": "10:00",
        "tech_days_before": 2,
        "tech_send_time": "12:00",
    }
    
    # Mock producer contact
    producer = {
        "contact_id": 10,
        "name": "Producer",
        "phone": "+972501234567"
    }
    
    # Mock existing INIT job (created before load_in_time was added)
    existing_init_job = {
        "job_id": "existing-job-456",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 102,
        "status": "scheduled",
        "send_at": datetime(2024, 1, 18, 10, 0, tzinfo=ZoneInfo("UTC")),
    }
    
    with patch.object(EventRepository, "get_event_by_id", return_value=event_with_load_in):
        with patch.object(SchedulerSettingsRepository, "get_or_create_settings", return_value=settings):
            with patch.object(ContactRepository, "get_contact_by_id", return_value=producer):
                with patch("app.services.scheduler_job_builder.ScheduledMessageRepository") as MockScheduledRepo:
                    # Mock that existing INIT job exists
                    mock_scheduled_repo = MockScheduledRepo.return_value
                    mock_scheduled_repo.find_job_for_event.return_value = existing_init_job
                    
                    result = build_or_update_jobs_for_event(org_id=1, event_id=102)
                    
                    # INIT should be skipped
                    assert result["init_status"] == "skipped"
                    assert result["init_skip_reason"] == SKIP_REASON_HAS_LOAD_IN_TIME
                    
                    # Verify that update_status was called to mark it as skipped
                    mock_scheduled_repo.update_status.assert_called_once()
                    call_args = mock_scheduled_repo.update_status.call_args
                    assert call_args[0][0] == "existing-job-456"
                    assert call_args[1]["status"] == "skipped"
                    assert "load_in_time" in call_args[1]["last_error"]
