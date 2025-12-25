"""
Tests for scheduler send-now functionality.

This module tests the manual "Send Now" feature which bypasses:
- Scheduler settings (enabled_global, enabled_init, etc.)
- Weekend postponement rules
- Duplicate detection
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
os.environ.setdefault("CONTENT_SID_SHIFT_REMINDER", "HXSHIFT")

import pytest

from app.services.scheduler import SchedulerService
from app.time_utils import now_utc


@pytest.mark.asyncio
async def test_send_now_bypasses_weekend_rule():
    """Test that manual send-now bypasses weekend postponement."""
    scheduler = SchedulerService()
    
    # Create a Friday datetime (would normally be postponed)
    friday = datetime(2024, 12, 27, 9, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    friday_utc = friday.astimezone(ZoneInfo("UTC"))
    
    # Mock job scheduled for Friday
    job = {
        "job_id": "test-job-send-now-1",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": friday_utc,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    # Mock the recipient resolution to return valid data
    with patch.object(scheduler, "_resolve_recipient", return_value={
        "success": True,
        "phone": "+972501234567",
        "name": "Test Contact",
        "contact_id": 1
    }):
        # Mock the actual message sending to succeed
        with patch.object(scheduler, "_send_message", new_callable=AsyncMock, return_value={
            "success": True
        }):
            # Mock the scheduled_repo.update_status method
            with patch.object(scheduler.scheduled_repo, "update_status") as mock_update:
                result = await scheduler._send_now(job, friday_utc)
                
                # Should succeed (not postponed)
                assert result["success"] is True
                
                # Verify status was updated to sent (not postponed)
                mock_update.assert_called()
                call_args = mock_update.call_args
                assert call_args[1]["status"] == "sent"


@pytest.mark.asyncio
async def test_send_now_bypasses_disabled_settings():
    """Test that manual send-now works even when message type is disabled."""
    scheduler = SchedulerService()
    
    now = now_utc()
    
    # Mock job with INIT type (even if disabled in settings)
    job = {
        "job_id": "test-job-send-now-2",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": now,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    # Mock the recipient resolution to return valid data
    with patch.object(scheduler, "_resolve_recipient", return_value={
        "success": True,
        "phone": "+972501234567",
        "name": "Test Contact",
        "contact_id": 1
    }):
        # Mock the actual message sending to succeed
        with patch.object(scheduler, "_send_message", new_callable=AsyncMock, return_value={
            "success": True
        }):
            # Mock the scheduled_repo.update_status method
            with patch.object(scheduler.scheduled_repo, "update_status") as mock_update:
                result = await scheduler._send_now(job, now)
                
                # Should succeed (settings not checked)
                assert result["success"] is True
                
                # Verify status was updated to sent
                mock_update.assert_called()
                call_args = mock_update.call_args
                assert call_args[1]["status"] == "sent"


@pytest.mark.asyncio
async def test_send_now_blocks_on_missing_recipient():
    """Test that manual send-now still validates recipient phone."""
    scheduler = SchedulerService()
    
    now = now_utc()
    
    job = {
        "job_id": "test-job-send-now-3",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": now,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    # Mock the recipient resolution to return missing phone
    with patch.object(scheduler, "_resolve_recipient", return_value={
        "success": False,
        "error": "Missing phone number"
    }):
        # Mock the scheduled_repo.update_status method
        with patch.object(scheduler.scheduled_repo, "update_status") as mock_update:
            result = await scheduler._send_now(job, now)
            
            # Should fail with missing recipient
            assert result["success"] is False
            assert result["reason_code"] == "MISSING_RECIPIENT"
            assert "Missing phone" in result["error"]
            
            # Verify status was updated to blocked
            mock_update.assert_called()
            call_args = mock_update.call_args
            assert call_args[1]["status"] == "blocked"


@pytest.mark.asyncio
async def test_send_now_handles_send_failure():
    """Test that manual send-now handles send failures properly."""
    scheduler = SchedulerService()
    
    now = now_utc()
    
    job = {
        "job_id": "test-job-send-now-4",
        "org_id": 1,
        "message_type": "SHIFT_REMINDER",
        "event_id": 100,
        "shift_id": 200,
        "status": "scheduled",
        "send_at": now,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    # Mock the recipient resolution to return valid data
    with patch.object(scheduler, "_resolve_recipient", return_value={
        "success": True,
        "phone": "+972501234567",
        "name": "Test Employee",
        "contact_id": None
    }):
        # Mock the actual message sending to fail
        with patch.object(scheduler, "_send_message", new_callable=AsyncMock, return_value={
            "success": False,
            "error": "Twilio API error"
        }):
            # Mock the scheduled_repo.update_status method
            with patch.object(scheduler.scheduled_repo, "update_status") as mock_update:
                result = await scheduler._send_now(job, now)
                
                # Should fail with send error
                assert result["success"] is False
                assert result["reason_code"] == "SEND_FAILED"
                assert "Twilio API error" in result["error"]
                
                # Verify status was updated to failed
                mock_update.assert_called()
                call_args = mock_update.call_args
                assert call_args[1]["status"] == "failed"


@pytest.mark.asyncio
async def test_send_now_no_duplicate_check():
    """Test that manual send-now does NOT check for duplicates (can re-send)."""
    scheduler = SchedulerService()
    
    now = now_utc()
    
    job = {
        "job_id": "test-job-send-now-5",
        "org_id": 1,
        "message_type": "INIT",
        "event_id": 100,
        "shift_id": None,
        "status": "scheduled",
        "send_at": now,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    
    # Mock the recipient resolution to return valid data
    with patch.object(scheduler, "_resolve_recipient", return_value={
        "success": True,
        "phone": "+972501234567",
        "name": "Test Contact",
        "contact_id": 1
    }):
        # Mock the actual message sending to succeed
        with patch.object(scheduler, "_send_message", new_callable=AsyncMock, return_value={
            "success": True
        }):
            # Mock the duplicate check (which should NOT be called for send-now)
            with patch.object(scheduler, "_is_duplicate", return_value=True) as mock_dedupe:
                # Mock the scheduled_repo.update_status method
                with patch.object(scheduler.scheduled_repo, "update_status") as mock_update:
                    result = await scheduler._send_now(job, now)
                    
                    # Should succeed (duplicate check bypassed)
                    assert result["success"] is True
                    
                    # Verify _is_duplicate was NOT called
                    mock_dedupe.assert_not_called()
                    
                    # Verify status was updated to sent
                    mock_update.assert_called()
                    call_args = mock_update.call_args
                    assert call_args[1]["status"] == "sent"
