"""
Tests for scheduler.run_once() implementation.

This module tests the complete scheduler flow including:
- Weekend postponement for INIT messages only
- Retry logic with increments and max attempts
- Dedupe checks against messages table
- SELECT FOR UPDATE SKIP LOCKED for concurrent processing
"""

import os
from datetime import datetime, date, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from zoneinfo import ZoneInfo

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

from app.services.scheduler import SchedulerService
from app.time_utils import parse_local_time_to_utc, now_utc, utc_to_local_datetime


@pytest.mark.asyncio
async def test_weekend_postponement_friday_to_sunday():
    """Test that INIT messages scheduled on Friday are postponed to Sunday."""
    scheduler = SchedulerService()
    
    # Create a Friday datetime (in Israel timezone)
    friday = datetime(2024, 12, 27, 9, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))  # Friday
    friday_utc = friday.astimezone(ZoneInfo("UTC"))
    
    # Mock job scheduled for Friday
    job = {
        "job_id": "test-job-1",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": friday_utc,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    # Mock the scheduled_repo.update_send_at method
    with patch.object(scheduler.scheduled_repo, "update_send_at") as mock_update:
        result = scheduler._check_weekend_postponement(job["job_id"], friday_utc)
        
        # Should return new send_at (Sunday at 10:00)
        assert result is not None
        
        # Convert result to Israel time and check it's Sunday
        result_israel = utc_to_local_datetime(result)
        assert result_israel.weekday() == 6  # Sunday
        assert result_israel.hour == 10
        assert result_israel.minute == 0
        
        # Verify update_send_at was called
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0]
        assert call_args[0] == "test-job-1"


@pytest.mark.asyncio
async def test_weekend_postponement_saturday_to_sunday():
    """Test that INIT messages scheduled on Saturday are postponed to Sunday."""
    scheduler = SchedulerService()
    
    # Create a Saturday datetime (in Israel timezone)
    saturday = datetime(2024, 12, 28, 9, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))  # Saturday
    saturday_utc = saturday.astimezone(ZoneInfo("UTC"))
    
    job = {
        "job_id": "test-job-2",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": saturday_utc,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    with patch.object(scheduler.scheduled_repo, "update_send_at") as mock_update:
        result = scheduler._check_weekend_postponement(job["job_id"], saturday_utc)
        
        # Should return new send_at (Sunday at 10:00)
        assert result is not None
        
        # Convert result to Israel time and check it's Sunday
        result_israel = utc_to_local_datetime(result)
        assert result_israel.weekday() == 6  # Sunday
        assert result_israel.hour == 10
        assert result_israel.minute == 0
        
        # Verify update_send_at was called
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_weekend_postponement_not_applied_on_weekday():
    """Test that INIT messages on weekdays are not postponed."""
    scheduler = SchedulerService()
    
    # Create a Monday datetime (in Israel timezone)
    monday = datetime(2024, 12, 23, 9, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))  # Monday
    monday_utc = monday.astimezone(ZoneInfo("UTC"))
    
    job = {
        "job_id": "test-job-3",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": monday_utc,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    with patch.object(scheduler.scheduled_repo, "update_send_at") as mock_update:
        result = scheduler._check_weekend_postponement(job["job_id"], monday_utc)
        
        # Should not postpone (return None)
        assert result is None
        
        # Verify update_send_at was NOT called
        mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_retry_increments_attempt_count():
    """Test that failed sends increment attempt_count and set retry status."""
    scheduler = SchedulerService()
    
    now = now_utc()
    job = {
        "job_id": "test-job-retry-1",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": now,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    with patch.object(scheduler.scheduled_repo, "increment_attempt") as mock_increment, \
         patch.object(scheduler.scheduled_repo, "update_send_at") as mock_update_send_at, \
         patch.object(scheduler.scheduled_repo, "update_status") as mock_update_status:
        
        result = scheduler._handle_send_failure(job, "Test error", now)
        
        # Should return "failed" (for this run, but will retry)
        assert result == "failed"
        
        # Verify increment_attempt was called
        mock_increment.assert_called_once_with("test-job-retry-1")
        
        # Verify send_at was updated (for retry)
        mock_update_send_at.assert_called_once()
        call_args = mock_update_send_at.call_args[0]
        assert call_args[0] == "test-job-retry-1"
        # Check that retry_at is approximately now + 10 minutes
        retry_at = call_args[1]
        time_diff = (retry_at - now).total_seconds()
        assert 590 <= time_diff <= 610  # 10 minutes +/- 10 seconds tolerance
        
        # Verify status was set to "retrying"
        mock_update_status.assert_called_once()
        status_call = mock_update_status.call_args
        assert status_call[0][0] == "test-job-retry-1"
        assert status_call[1]["status"] == "retrying"


@pytest.mark.asyncio
async def test_retry_fails_after_max_attempts():
    """Test that jobs are marked as permanently failed after max_attempts."""
    scheduler = SchedulerService()
    
    now = now_utc()
    job = {
        "job_id": "test-job-retry-max",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "retrying",
        "send_at": now,
        "attempt_count": 2,  # Already 2 attempts
        "max_attempts": 3,
    }
    
    with patch.object(scheduler.scheduled_repo, "increment_attempt") as mock_increment, \
         patch.object(scheduler.scheduled_repo, "update_send_at") as mock_update_send_at, \
         patch.object(scheduler.scheduled_repo, "update_status") as mock_update_status:
        
        result = scheduler._handle_send_failure(job, "Test error", now)
        
        # Should return "failed" (permanent failure)
        assert result == "failed"
        
        # Verify increment_attempt was called
        mock_increment.assert_called_once_with("test-job-retry-max")
        
        # Verify send_at was NOT updated (no more retries)
        mock_update_send_at.assert_not_called()
        
        # Verify status was set to "failed" (not "retrying")
        mock_update_status.assert_called_once()
        status_call = mock_update_status.call_args
        assert status_call[0][0] == "test-job-retry-max"
        assert status_call[1]["status"] == "failed"
        assert "Max attempts" in status_call[1]["last_error"]


@pytest.mark.asyncio
async def test_dedupe_skips_already_sent_messages():
    """Test that jobs are skipped if the message was already sent manually."""
    scheduler = SchedulerService()
    
    # Mock that a message already exists
    with patch("app.services.scheduler.get_session") as mock_session:
        mock_execute = Mock()
        mock_execute.scalar.return_value = 1  # Count > 0 means duplicate
        
        mock_session_instance = MagicMock()
        mock_session_instance.__enter__.return_value = mock_session_instance
        mock_session_instance.execute.return_value = mock_execute
        mock_session.return_value = mock_session_instance
        
        result = scheduler._is_duplicate(
            org_id=1,
            message_type="INIT",
            event_id=100,
            shift_id=None
        )
        
        # Should return True (is duplicate)
        assert result is True


@pytest.mark.asyncio
async def test_dedupe_allows_new_messages():
    """Test that jobs are not skipped if the message hasn't been sent."""
    scheduler = SchedulerService()
    
    # Mock that no message exists
    with patch("app.services.scheduler.get_session") as mock_session:
        mock_execute = Mock()
        mock_execute.scalar.return_value = 0  # Count = 0 means not duplicate
        
        mock_session_instance = MagicMock()
        mock_session_instance.__enter__.return_value = mock_session_instance
        mock_session_instance.execute.return_value = mock_execute
        mock_session.return_value = mock_session_instance
        
        result = scheduler._is_duplicate(
            org_id=1,
            message_type="INIT",
            event_id=100,
            shift_id=None
        )
        
        # Should return False (not a duplicate)
        assert result is False


@pytest.mark.asyncio
async def test_skip_locked_query_structure():
    """Test that the due jobs query includes FOR UPDATE SKIP LOCKED."""
    scheduler = SchedulerService()
    
    # This test verifies the query structure by inspecting the SQL
    # We can't easily test actual locking behavior in unit tests
    
    with patch("app.services.scheduler.get_session") as mock_session:
        mock_execute = Mock()
        mock_execute.fetchall.return_value = []  # No jobs found
        
        mock_session_instance = MagicMock()
        mock_session_instance.__enter__.return_value = mock_session_instance
        mock_session_instance.execute.return_value = mock_execute
        mock_session.return_value = mock_session_instance
        
        now = now_utc()
        result = scheduler._get_due_jobs_with_lock(org_id=1, now=now)
        
        # Verify execute was called
        assert mock_session_instance.execute.called
        
        # Get the first SQL query that was executed (the SELECT with FOR UPDATE)
        first_call = mock_session_instance.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        
        # Verify the query includes FOR UPDATE SKIP LOCKED
        assert "FOR UPDATE SKIP LOCKED" in sql_text.upper()
        assert "status in ('scheduled', 'retrying')" in sql_text.lower()
        assert "is_enabled" in sql_text.lower()


@pytest.mark.asyncio
async def test_resolve_recipient_init_prefers_technical():
    """Test that INIT messages prefer technical contact over producer."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-resolve-1",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
    }
    
    mock_event = {
        "event_id": 100,
        "technical_contact_id": 200,
        "producer_contact_id": 300,
    }
    
    mock_technical = {
        "contact_id": 200,
        "name": "Tech Person",
        "phone": "0501234567",
    }
    
    with patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.contacts_repo, "get_contact_by_id", return_value=mock_technical):
        
        result = scheduler._resolve_recipient(job)
        
        assert result["success"] is True
        assert result["name"] == "Tech Person"
        assert result["contact_id"] == 200
        assert "+972" in result["phone"]  # Should be normalized


@pytest.mark.asyncio
async def test_resolve_recipient_init_fallback_to_producer():
    """Test that INIT messages fall back to producer when technical has no phone."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-resolve-2",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
    }
    
    mock_event = {
        "event_id": 100,
        "technical_contact_id": 200,
        "producer_contact_id": 300,
    }
    
    mock_technical = {
        "contact_id": 200,
        "name": "Tech Person",
        "phone": "",  # No phone
    }
    
    mock_producer = {
        "contact_id": 300,
        "name": "Producer",
        "phone": "0509876543",
    }
    
    def get_contact_side_effect(org_id, contact_id):
        if contact_id == 200:
            return mock_technical
        elif contact_id == 300:
            return mock_producer
        return None
    
    with patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.contacts_repo, "get_contact_by_id", side_effect=get_contact_side_effect):
        
        result = scheduler._resolve_recipient(job)
        
        assert result["success"] is True
        assert result["name"] == "Producer"
        assert result["contact_id"] == 300


@pytest.mark.asyncio
async def test_resolve_recipient_blocks_when_phone_missing():
    """Test that jobs are blocked when recipient phone is missing."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-resolve-blocked",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
    }
    
    mock_event = {
        "event_id": 100,
        "technical_contact_id": None,
        "producer_contact_id": 300,
    }
    
    mock_producer = {
        "contact_id": 300,
        "name": "Producer",
        "phone": "",  # No phone
    }
    
    with patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.contacts_repo, "get_contact_by_id", return_value=mock_producer):
        
        result = scheduler._resolve_recipient(job)
        
        assert result["success"] is False
        assert "Missing phone" in result["error"]


@pytest.mark.asyncio
async def test_process_job_respects_disabled_message_types():
    """Test that jobs are skipped when their message type is disabled in settings."""
    scheduler = SchedulerService()
    
    now = now_utc()
    job = {
        "job_id": "test-disabled-1",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": now,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    settings = {
        "enabled_global": True,
        "enabled_init": False,  # INIT disabled
        "enabled_tech": True,
        "enabled_shift": True,
    }
    
    with patch.object(scheduler.scheduled_repo, "update_status") as mock_update_status:
        result = await scheduler._process_job(job, settings, now)
        
        # Should skip the job
        assert result == "skipped"
        
        # Verify status was updated to "skipped"
        mock_update_status.assert_called_once()
        call_args = mock_update_status.call_args
        assert call_args[0][0] == "test-disabled-1"
        assert call_args[1]["status"] == "skipped"
