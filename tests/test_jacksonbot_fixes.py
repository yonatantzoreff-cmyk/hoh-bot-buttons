"""
Tests for JacksonBot UI fixes (Phases 1-6).
Covers:
- PHASE 1: Follow-up flow (webhook → status → ack)
- PHASE 2: Shift creation without employee (nullable employee_id)
- PHASE 4: Message routing (technical → producer fallback)
- PHASE 3: Contacts endpoint includes phone numbers
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# Set up test environment before imports
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

from app.hoh_service import HOHService
from app.repositories import EmployeeShiftRepository, ContactRepository
from app.time_utils import now_utc


# PHASE 2: Test shift creation without employee
def test_shift_creation_nullable_employee_id():
    """Test that shifts can be created with employee_id=None."""
    repo = EmployeeShiftRepository()
    
    # Mock session to avoid actual DB operations
    with patch('app.repositories.get_session') as mock_session:
        mock_result = Mock()
        mock_result.scalar_one.return_value = 123
        
        mock_exec = Mock(return_value=mock_result)
        mock_context = MagicMock()
        mock_context.__enter__.return_value.execute = mock_exec
        mock_context.__enter__.return_value.commit = Mock()
        mock_session.return_value = mock_context
        
        # Mock the scheduler job builder to avoid additional DB calls
        with patch('app.services.scheduler_job_builder.build_or_update_jobs_for_shifts'):
            # Create shift with None employee_id (PHASE 2)
            shift_id = repo.create_shift(
                org_id=1,
                event_id=1,
                employee_id=None,  # Nullable - empty shift
                call_time=now_utc(),
                shift_role=None,
                notes="Test shift",
            )
            
            assert shift_id == 123
            # Verify that execute was called with None for employee_id
            call_args = mock_exec.call_args
            assert call_args[0][1]['employee_id'] is None


def test_shift_creation_with_employee_id():
    """Test that shifts can still be created with a valid employee_id."""
    repo = EmployeeShiftRepository()
    
    with patch('app.repositories.get_session') as mock_session:
        mock_result = Mock()
        mock_result.scalar_one.return_value = 124
        
        mock_exec = Mock(return_value=mock_result)
        mock_context = MagicMock()
        mock_context.__enter__.return_value.execute = mock_exec
        mock_context.__enter__.return_value.commit = Mock()
        mock_session.return_value = mock_context
        
        # Mock the scheduler job builder to avoid additional DB calls
        with patch('app.services.scheduler_job_builder.build_or_update_jobs_for_shifts'):
            # Create shift with valid employee_id
            shift_id = repo.create_shift(
                org_id=1,
                event_id=1,
                employee_id=42,  # Valid employee
                call_time=now_utc(),
                shift_role="Setup",
                notes="Setup shift",
            )
            
            assert shift_id == 124
            call_args = mock_exec.call_args
            assert call_args[0][1]['employee_id'] == 42


# PHASE 1: Test follow-up flow
@pytest.mark.asyncio
async def test_follow_up_updates_event_status():
    """Test that 'אני לא יודע' action updates event status to 'follow_up'."""
    hoh = HOHService()
    
    # Mock dependencies
    with patch.object(hoh.conversations, 'get_open_conversation') as mock_get_conv, \
         patch.object(hoh.conversations, 'update_pending_data_fields') as mock_update_fields, \
         patch.object(hoh.events, 'update_event') as mock_update_event, \
         patch.object(hoh.contacts, 'get_contact_by_id') as mock_get_contact, \
         patch.object(hoh.messages, 'log_message') as mock_log_msg, \
         patch('app.hoh_service.twilio_client') as mock_twilio:
        
        # Setup mocks
        mock_get_conv.return_value = {'conversation_id': 1, 'pending_data_fields': {}}
        mock_get_contact.return_value = {'contact_id': 1, 'name': 'Test', 'phone': '+972501234567'}
        
        mock_response = Mock()
        mock_response.sid = 'SM123'
        mock_twilio.send_content_message.return_value = mock_response
        
        # Call follow-up handler
        await hoh._handle_not_sure(
            event_id=1,
            contact_id=1,
            conversation_id=1,
            org_id=1,
        )
        
        # PHASE 1: Verify event status was updated to 'follow_up'
        assert mock_update_event.called
        call_args = mock_update_event.call_args
        assert call_args[1]['status'] == 'follow_up'
        assert 'next_followup_at' in call_args[1]
        
        # Verify acknowledgment message was sent
        assert mock_twilio.send_content_message.called
        
        # Verify message was logged
        assert mock_log_msg.called


@pytest.mark.asyncio
async def test_follow_up_sends_acknowledgment():
    """Test that follow-up action sends acknowledgment message."""
    hoh = HOHService()
    
    with patch.object(hoh.conversations, 'get_open_conversation') as mock_get_conv, \
         patch.object(hoh.conversations, 'update_pending_data_fields'), \
         patch.object(hoh.events, 'update_event'), \
         patch.object(hoh.contacts, 'get_contact_by_id') as mock_get_contact, \
         patch.object(hoh.messages, 'log_message') as mock_log_msg, \
         patch('app.hoh_service.twilio_client') as mock_twilio:
        
        mock_get_conv.return_value = {'conversation_id': 1, 'pending_data_fields': {}}
        mock_get_contact.return_value = {'contact_id': 1, 'name': 'Test', 'phone': '+972501234567'}
        
        mock_response = Mock()
        mock_response.sid = 'SM123'
        mock_twilio.send_content_message.return_value = mock_response
        
        await hoh._handle_not_sure(
            event_id=1,
            contact_id=1,
            conversation_id=1,
            org_id=1,
        )
        
        # PHASE 1: Verify Twilio message was sent
        assert mock_twilio.send_content_message.called
        call_args = mock_twilio.send_content_message.call_args
        assert call_args[1]['to'] == '+972501234567'
        
        # Verify message was logged with SID
        assert mock_log_msg.called
        log_call_args = mock_log_msg.call_args
        assert log_call_args[1]['whatsapp_msg_sid'] == 'SM123'
        assert log_call_args[1]['direction'] == 'outgoing'


# PHASE 4: Test message routing logic
@pytest.mark.asyncio
async def test_message_routing_prefers_technical():
    """Test that messages are sent to technical contact if available."""
    hoh = HOHService()
    
    with patch.object(hoh.orgs, 'get_org_by_id') as mock_get_org, \
         patch.object(hoh.events, 'get_event_by_id') as mock_get_event, \
         patch.object(hoh.contacts, 'get_contact_by_id') as mock_get_contact, \
         patch.object(hoh, '_ensure_conversation') as mock_ensure_conv, \
         patch.object(hoh.conversations, 'update_conversation_state'), \
         patch.object(hoh.messages, 'log_message'), \
         patch('app.hoh_service.twilio_client') as mock_twilio:
        
        # Setup: Event with both technical and producer
        mock_get_org.return_value = {'org_id': 1, 'name': 'Test Org'}
        mock_get_event.return_value = {
            'event_id': 1,
            'name': 'Test Event',
            'event_date': datetime(2024, 1, 15).date(),
            'show_time': datetime(2024, 1, 15, 21, 0),
            'technical_contact_id': 10,  # Has technical
            'producer_contact_id': 20,
        }
        
        # Technical contact with valid phone
        def get_contact_side_effect(org_id, contact_id):
            if contact_id == 10:
                return {'contact_id': 10, 'name': 'Technical', 'phone': '+972501111111'}
            elif contact_id == 20:
                return {'contact_id': 20, 'name': 'Producer', 'phone': '+972502222222'}
            return None
        
        mock_get_contact.side_effect = get_contact_side_effect
        mock_ensure_conv.return_value = 1
        
        mock_response = Mock()
        mock_response.sid = 'SM456'
        mock_twilio.send_content_message.return_value = mock_response
        
        # Send INIT
        await hoh.send_init_for_event(event_id=1, org_id=1)
        
        # PHASE 4: Verify message was sent to technical, not producer
        assert mock_twilio.send_content_message.called
        call_args = mock_twilio.send_content_message.call_args
        assert call_args[1]['to'] == '+972501111111'  # Technical phone


@pytest.mark.asyncio
async def test_message_routing_fallback_to_producer():
    """Test that messages fall back to producer when no valid technical."""
    hoh = HOHService()
    
    with patch.object(hoh.orgs, 'get_org_by_id') as mock_get_org, \
         patch.object(hoh.events, 'get_event_by_id') as mock_get_event, \
         patch.object(hoh.contacts, 'get_contact_by_id') as mock_get_contact, \
         patch.object(hoh, '_ensure_conversation') as mock_ensure_conv, \
         patch.object(hoh.conversations, 'update_conversation_state'), \
         patch.object(hoh.messages, 'log_message'), \
         patch('app.hoh_service.twilio_client') as mock_twilio:
        
        # Setup: Event with no technical (or technical without phone)
        mock_get_org.return_value = {'org_id': 1, 'name': 'Test Org'}
        mock_get_event.return_value = {
            'event_id': 1,
            'name': 'Test Event',
            'event_date': datetime(2024, 1, 15).date(),
            'show_time': datetime(2024, 1, 15, 21, 0),
            'technical_contact_id': None,  # No technical
            'producer_contact_id': 20,
        }
        
        mock_get_contact.return_value = {'contact_id': 20, 'name': 'Producer', 'phone': '+972502222222'}
        mock_ensure_conv.return_value = 1
        
        mock_response = Mock()
        mock_response.sid = 'SM789'
        mock_twilio.send_content_message.return_value = mock_response
        
        # Send INIT
        await hoh.send_init_for_event(event_id=1, org_id=1)
        
        # PHASE 4: Verify message was sent to producer as fallback
        assert mock_twilio.send_content_message.called
        call_args = mock_twilio.send_content_message.call_args
        assert call_args[1]['to'] == '+972502222222'  # Producer phone


# PHASE 3: Test contacts endpoint includes phone numbers
def test_contacts_by_role_includes_phone():
    """Test that list_contacts_by_role includes phone numbers."""
    hoh = HOHService()
    
    with patch.object(hoh.contacts, 'list_contacts') as mock_list:
        mock_list.return_value = [
            {'contact_id': 1, 'name': 'Producer 1', 'phone': '+972501111111', 'role': 'producer'},
            {'contact_id': 2, 'name': 'Technical 1', 'phone': '+972502222222', 'role': 'technical'},
            {'contact_id': 3, 'name': 'Producer 2', 'phone': '+972503333333', 'role': 'producer'},
        ]
        
        result = hoh.list_contacts_by_role(org_id=1)
        
        # PHASE 3: Verify structure includes phone
        assert 'producer' in result
        assert 'technical' in result
        assert len(result['producer']) == 2
        assert len(result['technical']) == 1
        
        # Verify phone numbers are included
        assert result['producer'][0]['phone'] == '+972501111111'
        assert result['producer'][1]['phone'] == '+972503333333'
        assert result['technical'][0]['phone'] == '+972502222222'


def test_contacts_data_structure():
    """Test that contacts have the expected structure for dropdowns."""
    hoh = HOHService()
    
    with patch.object(hoh.contacts, 'list_contacts') as mock_list:
        mock_list.return_value = [
            {
                'contact_id': 1,
                'name': 'John Doe',
                'phone': '+972501234567',
                'role': 'producer',
            },
        ]
        
        result = hoh.list_contacts_by_role(org_id=1)
        contact = result['producer'][0]
        
        # PHASE 3: Verify all required fields for dropdown
        assert 'contact_id' in contact
        assert 'name' in contact
        assert 'phone' in contact
        assert 'role' in contact
        assert contact['phone'] is not None and contact['phone'] != ''
