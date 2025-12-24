"""Tests for job_key upsert behavior in scheduled messages."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from app.repositories import ScheduledMessageRepository


@patch("app.repositories.get_session")
def test_create_scheduled_message_upsert_behavior(mock_get_session):
    """Test that create_scheduled_message uses ON CONFLICT for idempotency."""
    # Setup mock session
    mock_session = MagicMock()
    mock_get_session.return_value.__enter__.return_value = mock_session
    
    # Setup mock result (simulate RETURNING job_id)
    mock_result = Mock()
    mock_result.scalar_one.return_value = 123  # Simulated auto-generated job_id
    mock_session.execute.return_value = mock_result
    
    # Create repository and call the method
    repo = ScheduledMessageRepository()
    now = datetime.utcnow()
    
    job_id = repo.create_scheduled_message(
        job_key="org_1_event_42_INIT_abc123",
        org_id=1,
        message_type="INIT",
        send_at=now + timedelta(days=7),
        event_id=42,
        is_enabled=True,
        max_attempts=3
    )
    
    # Verify the returned job_id is an integer
    assert isinstance(job_id, int)
    assert job_id == 123
    
    # Verify the SQL query was executed
    assert mock_session.execute.called
    call_args = mock_session.execute.call_args
    
    # Verify ON CONFLICT clause is in the query
    query_text = str(call_args[0][0])
    assert "ON CONFLICT" in query_text
    assert "job_key" in query_text
    assert "DO UPDATE" in query_text
    
    # Verify job_key parameter was passed (not job_id)
    params = call_args[0][1]
    assert "job_key" in params
    assert params["job_key"] == "org_1_event_42_INIT_abc123"
    assert "org_id" in params
    assert params["org_id"] == 1


@patch("app.repositories.get_session")
def test_get_scheduled_message_uses_numeric_job_id(mock_get_session):
    """Test that get_scheduled_message accepts integer job_id."""
    # Setup mock session
    mock_session = MagicMock()
    mock_get_session.return_value.__enter__.return_value = mock_session
    
    # Setup mock result
    mock_result = Mock()
    mock_row_mapping = {
        "job_id": 123,
        "job_key": "org_1_event_42_INIT_abc123",
        "org_id": 1,
        "message_type": "INIT",
        "status": "scheduled"
    }
    mock_result.mappings.return_value.first.return_value = mock_row_mapping
    mock_session.execute.return_value = mock_result
    
    # Call the method with integer job_id
    repo = ScheduledMessageRepository()
    job = repo.get_scheduled_message(123)
    
    # Verify result
    assert job is not None
    assert job["job_id"] == 123
    assert job["job_key"] == "org_1_event_42_INIT_abc123"
    
    # Verify the query was called with integer
    call_args = mock_session.execute.call_args
    params = call_args[0][1]
    assert "job_id" in params
    assert params["job_id"] == 123
    assert isinstance(params["job_id"], int)


@patch("app.repositories.get_session")
def test_update_methods_accept_numeric_job_id(mock_get_session):
    """Test that update methods accept integer job_id."""
    # Setup mock session
    mock_session = MagicMock()
    mock_get_session.return_value.__enter__.return_value = mock_session
    
    repo = ScheduledMessageRepository()
    now = datetime.utcnow()
    
    # Test update_send_at
    repo.update_send_at(123, now)
    call_args = mock_session.execute.call_args
    params = call_args[0][1]
    assert params["job_id"] == 123
    assert isinstance(params["job_id"], int)
    
    # Test update_status
    repo.update_status(456, "sent")
    call_args = mock_session.execute.call_args
    params = call_args[0][1]
    assert params["job_id"] == 456
    assert isinstance(params["job_id"], int)
    
    # Test set_enabled
    repo.set_enabled(789, False)
    call_args = mock_session.execute.call_args
    params = call_args[0][1]
    assert params["job_id"] == 789
    assert isinstance(params["job_id"], int)
