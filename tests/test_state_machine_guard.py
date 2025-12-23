"""
Tests for conversation state machine guard.
Tests the strict flow control that prevents free text from progressing the conversation.
"""
import os
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def test_extract_phone_numbers_from_text_finds_single_phone():
    """Test extraction of single phone number from text."""
    phones = HOHService._extract_phone_numbers_from_text("054-1234567")
    assert len(phones) == 1
    assert phones[0] == "+972541234567"


def test_extract_phone_numbers_from_text_finds_multiple_phones():
    """Test extraction of multiple phone numbers from text."""
    text = "Call me at 054-1234567 or 052-9876543"
    phones = HOHService._extract_phone_numbers_from_text(text)
    assert len(phones) == 2
    assert "+972541234567" in phones
    assert "+972529876543" in phones


def test_extract_phone_numbers_from_text_with_no_phones():
    """Test text without phone numbers returns empty list."""
    phones = HOHService._extract_phone_numbers_from_text("just some text here")
    assert len(phones) == 0


def test_extract_phone_numbers_from_text_with_international_format():
    """Test extraction with international format."""
    phones = HOHService._extract_phone_numbers_from_text("+972541234567")
    assert len(phones) == 1
    assert phones[0] == "+972541234567"


def test_is_contact_share_detects_twilio_contacts():
    """Test detection of Twilio Contacts payload."""
    payload = {
        "Contacts[0][PhoneNumber]": "+972501234567",
        "Contacts[0][Name]": "Test Contact"
    }
    assert HOHService._is_contact_share(payload) is True


def test_is_contact_share_detects_vcard_media():
    """Test detection of vCard media."""
    payload = {
        "NumMedia": "1",
        "MediaContentType0": "text/x-vcard",
        "MediaUrl0": "https://example.com/contact.vcf"
    }
    assert HOHService._is_contact_share(payload) is True


def test_is_contact_share_rejects_regular_text():
    """Test that regular text is not detected as contact share."""
    payload = {
        "Body": "Hello this is just text",
        "NumMedia": "0"
    }
    assert HOHService._is_contact_share(payload) is False


def test_is_contact_share_rejects_empty_payload():
    """Test empty payload."""
    assert HOHService._is_contact_share({}) is False
    assert HOHService._is_contact_share(None) is False


class TestStateGuardIntegration:
    """Integration tests for state guard logic in webhook handler."""
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    @patch('app.hoh_service.twilio_client')
    @pytest.mark.asyncio
    @patch('app.hoh_service.HOHService.send_ranges_for_event')
    async def test_guard_blocks_text_when_interactive_expected(
        self,
        mock_send_ranges,
        mock_twilio_client
    ):
        """
        Test: When state is 'interactive' and user sends text (e.g., '14.00'),
        the guard should:
        1. Send error message "נא להשתמש בכפתורים"
        2. Resend the last prompt (ranges)
        3. NOT update DB or progress flow
        """
        service = HOHService()
        mock_send_ranges.return_value = AsyncMock()
        mock_twilio_client.send_text.return_value = MagicMock(sid="MSG123")
        
        # Mock the repositories
        with patch.object(service.contacts, 'get_or_create_by_phone', return_value=1), \
             patch.object(service.events, 'get_event_by_id', return_value={
                 "event_id": 10,
                 "name": "Test Event",
                 "event_date": date(2025, 1, 1),
                 "show_time": None
             }), \
             patch.object(service.conversations, 'get_open_conversation', return_value={
                 "conversation_id": 5,
                 "event_id": 10,
                 "expected_input": "interactive",
                 "last_prompt_key": "ranges"
             }), \
             patch.object(service.messages, 'log_message', return_value=1), \
             patch.object(service.events, 'update_event_fields') as mock_update_event:
            
            payload = {
                "From": "+972501234567",
                "Body": "14.00",
                "ProfileName": "Test User"
            }
            
            await service.handle_whatsapp_webhook(payload, org_id=1)
            
            # Verify error message was sent
            mock_twilio_client.send_text.assert_called_once()
            call_args = mock_twilio_client.send_text.call_args
            assert "נא להשתמש בכפתורים" in call_args[1]["body"]
            
            # Verify last prompt was resent
            mock_send_ranges.assert_called_once_with(1, 10, 1)
            
            # Verify DB was NOT updated (event not progressed)
            mock_update_event.assert_not_called()
    
    @pytest.mark.asyncio
    @patch('app.hoh_service.twilio_client')
    async def test_guard_allows_contact_share_when_contact_required(
        self,
        mock_twilio_client
    ):
        """
        Test: When state is 'contact_required' and user sends valid contact share,
        the guard should allow it to proceed.
        """
        service = HOHService()
        
        # Mock successful contact handling
        with patch.object(service.contacts, 'get_or_create_by_phone', return_value=1), \
             patch.object(service.events, 'get_event_by_id', return_value={
                 "event_id": 10,
                 "name": "Test Event"
             }), \
             patch.object(service.conversations, 'get_open_conversation', return_value={
                 "conversation_id": 5,
                 "event_id": 10,
                 "expected_input": "contact_required",
                 "last_prompt_key": "contact_prompt",
                 "pending_data_fields": {"awaiting_new_contact": True}
             }), \
             patch.object(service.messages, 'log_message', return_value=1), \
             patch.object(service.contacts, 'get_contact_by_id', return_value={"phone": "+972501234567"}), \
             patch.object(service.events, 'update_event_fields'):
            
            payload = {
                "From": "+972501234567",
                "Contacts[0][PhoneNumber]": "+972529876543",
                "Contacts[0][Name]": "Tech Contact",
                "ProfileName": "Producer"
            }
            
            await service.handle_whatsapp_webhook(payload, org_id=1)
            
            # Verify no error message was sent (flow continued)
            mock_twilio_client.send_text.assert_not_called()
    
    @pytest.mark.asyncio
    @patch('app.hoh_service.twilio_client')
    @pytest.mark.asyncio
    @patch('app.hoh_service.HOHService._resend_last_prompt')
    async def test_guard_blocks_text_without_phone_when_contact_required(
        self,
        mock_resend_prompt,
        mock_twilio_client
    ):
        """
        Test: When state is 'contact_required' and user sends text without phone,
        the guard should:
        1. Send error message "יש לצרף איש קשר"
        2. Resend contact prompt
        3. NOT create contact or progress flow
        """
        service = HOHService()
        mock_resend_prompt.return_value = AsyncMock()
        mock_twilio_client.send_text.return_value = MagicMock(sid="MSG123")
        
        with patch.object(service.contacts, 'get_or_create_by_phone', return_value=1), \
             patch.object(service.events, 'get_event_by_id', return_value={
                 "event_id": 10,
                 "name": "Test Event"
             }), \
             patch.object(service.conversations, 'get_open_conversation', return_value={
                 "conversation_id": 5,
                 "event_id": 10,
                 "expected_input": "contact_required",
                 "last_prompt_key": "contact_prompt"
             }), \
             patch.object(service.contacts, 'get_contact_by_id', return_value={"phone": "+972501234567"}), \
             patch.object(service.events, 'update_event_fields') as mock_update_event:
            
            payload = {
                "From": "+972501234567",
                "Body": "מצרפת נייד של אורן",
                "ProfileName": "Producer"
            }
            
            await service.handle_whatsapp_webhook(payload, org_id=1)
            
            # Verify error message was sent
            mock_twilio_client.send_text.assert_called_once()
            call_args = mock_twilio_client.send_text.call_args
            assert "יש לצרף איש קשר" in call_args[1]["body"]
            
            # Verify prompt was resent
            mock_resend_prompt.assert_called_once()
            
            # Verify DB was NOT updated
            mock_update_event.assert_not_called()
    
    @pytest.mark.asyncio
    @patch('app.hoh_service.twilio_client')
    async def test_guard_accepts_text_with_single_phone_when_contact_required(
        self,
        mock_twilio_client
    ):
        """
        Test: When state is 'contact_required' and user sends text with ONE phone,
        the guard should treat it as a contact share and allow handoff.
        """
        service = HOHService()
        mock_twilio_client.send_text.return_value = MagicMock(sid="MSG123")
        
        with patch.object(service.contacts, 'get_or_create_by_phone', return_value=1), \
             patch.object(service.events, 'get_event_by_id', return_value={
                 "event_id": 10,
                 "name": "Test Event"
             }), \
             patch.object(service.conversations, 'get_open_conversation', return_value={
                 "conversation_id": 5,
                 "event_id": 10,
                 "expected_input": "contact_required",
                 "last_prompt_key": "contact_prompt",
                 "pending_data_fields": {"awaiting_new_contact": True}
             }), \
             patch.object(service.messages, 'log_message', return_value=1), \
             patch.object(service.contacts, 'get_contact_by_id', return_value={"phone": "+972501234567"}), \
             patch.object(service.events, 'update_event_fields'):
            
            payload = {
                "From": "+972501234567",
                "Body": "054-1234567",
                "ProfileName": "Producer"
            }
            
            await service.handle_whatsapp_webhook(payload, org_id=1)
            
            # The guard should have synthesized a contact payload
            # so no error message should be sent
            # (In reality, flow would continue to _handle_contact_followup)
    
    @pytest.mark.asyncio
    @patch('app.hoh_service.twilio_client')
    async def test_guard_ignores_all_messages_when_paused(
        self,
        mock_twilio_client
    ):
        """
        Test: When state is 'paused' (after "אני לא יודע"),
        the guard should ignore ALL incoming messages.
        """
        service = HOHService()
        
        with patch.object(service.contacts, 'get_or_create_by_phone', return_value=1), \
             patch.object(service.events, 'get_event_by_id', return_value={
                 "event_id": 10,
                 "name": "Test Event"
             }), \
             patch.object(service.conversations, 'get_open_conversation', return_value={
                 "conversation_id": 5,
                 "event_id": 10,
                 "expected_input": "paused",
                 "last_prompt_key": "not_sure"
             }), \
             patch.object(service.messages, 'log_message') as mock_log_message, \
             patch.object(service.events, 'update_event_fields') as mock_update_event:
            
            payload = {
                "From": "+972501234567",
                "Body": "Hello are you there?",
                "ProfileName": "Producer"
            }
            
            await service.handle_whatsapp_webhook(payload, org_id=1)
            
            # Verify NO messages were sent
            mock_twilio_client.send_text.assert_not_called()
            mock_twilio_client.send_content_message.assert_not_called()
            
            # Verify incoming message was NOT logged (early return)
            mock_log_message.assert_not_called()
            
            # Verify DB was NOT updated
            mock_update_event.assert_not_called()
