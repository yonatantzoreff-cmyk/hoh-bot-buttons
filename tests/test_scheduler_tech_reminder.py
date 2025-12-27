"""
Tests for TECH_REMINDER scheduler implementation.

This module tests:
- TECH_REMINDER recipient resolution with fallback logic
- TECH_REMINDER sending through scheduler
- Duplicate detection with recipient-specific logic
"""

import os
from datetime import datetime
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
os.environ.setdefault("CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT", "HXTECH")

import pytest

from app.services.scheduler import SchedulerService
from app.time_utils import now_utc


@pytest.mark.asyncio
async def test_tech_reminder_recipient_uses_technical_contact():
    """Test that TECH_REMINDER uses technical contact when available."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-tech-1",
        "org_id": 1,
        "message_type": "TECH_REMINDER",
        "event_id": 100,
        "shift_id": None,
    }
    
    # Mock event with technical contact
    mock_event = {
        "event_id": 100,
        "technical_contact_id": 10,
        "producer_contact_id": 20,
    }
    
    # Mock technical contact with phone
    mock_technical = {
        "contact_id": 10,
        "name": "David Technician",
        "phone": "0501234567",
    }
    
    with patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.contacts_repo, "get_contact_by_id", return_value=mock_technical):
        
        result = scheduler._resolve_recipient(job)
        
        # Should use technical contact
        assert result["success"] is True
        assert result["phone"] == "+972501234567"
        assert result["name"] == "David Technician"
        assert result["contact_id"] == 10


@pytest.mark.asyncio
async def test_tech_reminder_recipient_falls_back_to_producer():
    """Test that TECH_REMINDER falls back to producer when technical contact has no phone."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-tech-2",
        "org_id": 1,
        "message_type": "TECH_REMINDER",
        "event_id": 100,
        "shift_id": None,
    }
    
    # Mock event with both contacts
    mock_event = {
        "event_id": 100,
        "technical_contact_id": 10,
        "producer_contact_id": 20,
    }
    
    # Mock technical contact WITHOUT phone
    mock_technical = {
        "contact_id": 10,
        "name": "David Technician",
        "phone": "",  # No phone
    }
    
    # Mock producer with phone
    mock_producer = {
        "contact_id": 20,
        "name": "Sarah Producer",
        "phone": "0507654321",
    }
    
    def get_contact_side_effect(org_id, contact_id):
        if contact_id == 10:
            return mock_technical
        elif contact_id == 20:
            return mock_producer
        return None
    
    with patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.contacts_repo, "get_contact_by_id", side_effect=get_contact_side_effect):
        
        result = scheduler._resolve_recipient(job)
        
        # Should fall back to producer
        assert result["success"] is True
        assert result["phone"] == "+972507654321"
        assert result["name"] == "Sarah Producer"
        assert result["contact_id"] == 20  # Producer contact_id


@pytest.mark.asyncio
async def test_tech_reminder_recipient_no_technical_assigned():
    """Test that TECH_REMINDER falls back to producer when no technical contact assigned."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-tech-3",
        "org_id": 1,
        "message_type": "TECH_REMINDER",
        "event_id": 100,
        "shift_id": None,
    }
    
    # Mock event with NO technical contact
    mock_event = {
        "event_id": 100,
        "technical_contact_id": None,
        "producer_contact_id": 20,
    }
    
    # Mock producer with phone
    mock_producer = {
        "contact_id": 20,
        "name": "Sarah Producer",
        "phone": "0507654321",
    }
    
    with patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.contacts_repo, "get_contact_by_id", return_value=mock_producer):
        
        result = scheduler._resolve_recipient(job)
        
        # Should use producer
        assert result["success"] is True
        assert result["phone"] == "+972507654321"
        assert result["name"] == "Sarah Producer"
        assert result["contact_id"] == 20


@pytest.mark.asyncio
async def test_tech_reminder_recipient_no_valid_phone():
    """Test that TECH_REMINDER returns error when neither contact has phone."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-tech-4",
        "org_id": 1,
        "message_type": "TECH_REMINDER",
        "event_id": 100,
        "shift_id": None,
    }
    
    # Mock event with both contacts
    mock_event = {
        "event_id": 100,
        "technical_contact_id": 10,
        "producer_contact_id": 20,
    }
    
    # Both contacts without phones
    mock_technical = {
        "contact_id": 10,
        "name": "David Technician",
        "phone": "",
    }
    
    mock_producer = {
        "contact_id": 20,
        "name": "Sarah Producer",
        "phone": None,
    }
    
    def get_contact_side_effect(org_id, contact_id):
        if contact_id == 10:
            return mock_technical
        elif contact_id == 20:
            return mock_producer
        return None
    
    with patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.contacts_repo, "get_contact_by_id", side_effect=get_contact_side_effect):
        
        result = scheduler._resolve_recipient(job)
        
        # Should return error
        assert result["success"] is False
        assert "Missing phone number" in result["error"]


@pytest.mark.asyncio
async def test_is_duplicate_tech_reminder_checks_contact_id():
    """Test that duplicate detection for TECH_REMINDER checks recipient contact_id."""
    scheduler = SchedulerService()
    
    # Mock the database query to return count > 0 (message exists)
    with patch("app.services.scheduler.get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1  # Message exists
        mock_session.execute.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_get_session.return_value = mock_session
        
        # Check duplicate for contact_id 10
        is_dup = scheduler._is_duplicate(
            org_id=1,
            message_type="TECH_REMINDER",
            event_id=100,
            shift_id=None,
            recipient_contact_id=10
        )
        
        assert is_dup is True
        
        # Verify SQL query includes contact_id parameter
        call_args = mock_session.execute.call_args
        query_params = call_args[0][1]
        assert query_params["contact_id"] == 10


@pytest.mark.asyncio
async def test_is_duplicate_init_checks_contact_id():
    """Test that duplicate detection for INIT checks recipient contact_id."""
    scheduler = SchedulerService()
    
    # Mock the database query
    with patch("app.services.scheduler.get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0  # No message exists
        mock_session.execute.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_get_session.return_value = mock_session
        
        # Check duplicate for contact_id 20
        is_dup = scheduler._is_duplicate(
            org_id=1,
            message_type="INIT",
            event_id=100,
            shift_id=None,
            recipient_contact_id=20
        )
        
        assert is_dup is False
        
        # Verify SQL query includes contact_id parameter
        call_args = mock_session.execute.call_args
        query_params = call_args[0][1]
        assert query_params["contact_id"] == 20


@pytest.mark.asyncio
async def test_is_duplicate_different_recipients_not_duplicate():
    """Test that same message type to different recipients is not a duplicate."""
    scheduler = SchedulerService()
    
    with patch("app.services.scheduler.get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_result = MagicMock()
        
        # First call: message sent to contact 10
        mock_result.scalar.return_value = 1  # Exists
        mock_session.execute.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = None
        mock_get_session.return_value = mock_session
        
        # Check for contact 10 - should be duplicate
        is_dup_10 = scheduler._is_duplicate(
            org_id=1,
            message_type="TECH_REMINDER",
            event_id=100,
            shift_id=None,
            recipient_contact_id=10
        )
        assert is_dup_10 is True
        
        # Reset mock for second check
        mock_result.scalar.return_value = 0  # Does not exist for contact 20
        
        # Check for contact 20 - should NOT be duplicate (different recipient)
        is_dup_20 = scheduler._is_duplicate(
            org_id=1,
            message_type="TECH_REMINDER",
            event_id=100,
            shift_id=None,
            recipient_contact_id=20
        )
        assert is_dup_20 is False


@pytest.mark.asyncio
async def test_send_tech_reminder_success():
    """Test successful TECH_REMINDER message sending."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-send-1",
        "org_id": 1,
        "message_type": "TECH_REMINDER",
        "event_id": 100,
        "shift_id": None,
    }
    
    # Mock payload
    mock_payload = {
        "to_phone": "whatsapp:+972501234567",
        "variables": {
            "1": "David",
            "2": "Test Event",
            "3": "01/01/2025",
            "4": "18:00",
            "5": "20:00",
            "6": "Employee",
            "7": "+972509999999",
        },
        "opening_employee_metadata": {
            "employee_name": "Test Employee",
        }
    }
    
    mock_event = {
        "event_id": 100,
        "name": "Test Event",
    }
    
    mock_twilio_response = MagicMock()
    mock_twilio_response.sid = "SM123456"
    
    with patch.object(scheduler.hoh, "build_tech_reminder_employee_payload", return_value=mock_payload), \
         patch.object(scheduler.events_repo, "get_event_by_id", return_value=mock_event), \
         patch.object(scheduler.hoh, "_ensure_conversation", return_value=1), \
         patch("app.twilio_client") as mock_twilio, \
         patch.object(scheduler.messages_repo, "log_message") as mock_log:
        
        mock_twilio.send_content_message.return_value = mock_twilio_response
        
        result = await scheduler._send_message(
            job=job,
            recipient_phone="+972501234567",
            recipient_name="David",
            recipient_contact_id=10,
            now=now_utc()
        )
        
        # Should succeed
        assert result["success"] is True
        
        # Verify Twilio was called
        mock_twilio.send_content_message.assert_called_once()
        call_kwargs = mock_twilio.send_content_message.call_args[1]
        assert call_kwargs["to"] == "whatsapp:+972501234567"
        # The content_sid comes from the environment variable set at test start
        assert "content_sid" in call_kwargs
        
        # Verify message was logged
        mock_log.assert_called_once()
        log_call = mock_log.call_args[1]
        assert log_call["org_id"] == 1
        assert log_call["event_id"] == 100
        assert log_call["contact_id"] == 10
        assert log_call["direction"] == "outgoing"


@pytest.mark.asyncio
async def test_send_tech_reminder_missing_employees():
    """Test TECH_REMINDER handles error when no employees assigned."""
    scheduler = SchedulerService()
    
    job = {
        "job_id": "test-send-2",
        "org_id": 1,
        "message_type": "TECH_REMINDER",
        "event_id": 100,
        "shift_id": None,
    }
    
    # Mock build_tech_reminder_employee_payload to raise ValueError
    with patch.object(
        scheduler.hoh, 
        "build_tech_reminder_employee_payload", 
        side_effect=ValueError("No employees assigned to this event")
    ):
        
        result = await scheduler._send_message(
            job=job,
            recipient_phone="+972501234567",
            recipient_name="David",
            recipient_contact_id=10,
            now=now_utc()
        )
        
        # Should fail gracefully
        assert result["success"] is False
        assert "No employees assigned" in result["error"]
