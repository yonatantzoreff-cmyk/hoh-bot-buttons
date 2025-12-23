"""
Tests for technical reminder with opening employee feature.
"""
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Set env vars before imports
os.environ["TWILIO_ACCOUNT_SID"] = "test_sid"
os.environ["TWILIO_AUTH_TOKEN"] = "test_token"
os.environ["TWILIO_MESSAGING_SERVICE_SID"] = "test_msid"
os.environ["CONTENT_SID_INIT"] = "test_init"
os.environ["CONTENT_SID_RANGES"] = "test_ranges"
os.environ["CONTENT_SID_HALVES"] = "test_halves"
os.environ["CONTENT_SID_CONFIRM"] = "test_confirm"
os.environ["CONTENT_SID_NOT_SURE"] = "test_not_sure"
os.environ["CONTENT_SID_CONTACT"] = "test_contact"
os.environ["CONTENT_SID_SHIFT_REMINDER"] = "test_reminder"
os.environ["CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT"] = "HX_test_tech_reminder"

from app.hoh_service import HOHService
from app.twilio_client import send_content_message


class TestTwilioClientGuard:
    """Test the content_variables guard in twilio_client."""
    
    def test_list_variables_rejected(self):
        """Test that list variables are rejected with clear error."""
        with pytest.raises(ValueError) as exc_info:
            send_content_message(
                to="+972501234567",
                content_sid="HX123",
                content_variables=["value1", "value2"]
            )
        
        assert "must be a dict" in str(exc_info.value).lower()
        assert "not a list" in str(exc_info.value).lower()
    
    def test_tuple_variables_rejected(self):
        """Test that tuple variables are rejected with clear error."""
        with pytest.raises(ValueError) as exc_info:
            send_content_message(
                to="+972501234567",
                content_sid="HX123",
                content_variables=("value1", "value2")
            )
        
        assert "must be a dict" in str(exc_info.value).lower()
        assert "tuple" in str(exc_info.value).lower()
    
    @patch("app.twilio_client.client")
    def test_dict_variables_accepted(self, mock_client):
        """Test that dict variables are accepted and passed correctly."""
        mock_message = MagicMock()
        mock_message.sid = "SM123"
        mock_client.messages.create.return_value = mock_message
        
        # Should not raise ValueError
        result = send_content_message(
            to="+972501234567",
            content_sid="HX123",
            content_variables={"1": "value1", "2": "value2"}
        )
        
        assert result is not None
        mock_client.messages.create.assert_called_once()


class TestBuildTechReminderPayload:
    """Test the build_tech_reminder_employee_payload function."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.service = HOHService()
    
    def test_missing_event_raises_error(self):
        """Test that missing event raises ValueError."""
        # Mock the get_event_with_contacts to return None
        self.service.get_event_with_contacts = MagicMock(return_value=None)
        
        with pytest.raises(ValueError) as exc_info:
            self.service.build_tech_reminder_employee_payload(org_id=1, event_id=999)
        
        assert "not found" in str(exc_info.value).lower()
    
    def test_missing_technical_contact_raises_error(self):
        """Test that missing technical contact raises ValueError."""
        # Mock event without technical_contact_id
        mock_event = {
            "event_id": 1,
            "name": "Test Event",
            "technical_contact_id": None,
        }
        self.service.get_event_with_contacts = MagicMock(return_value=mock_event)
        
        with pytest.raises(ValueError) as exc_info:
            self.service.build_tech_reminder_employee_payload(org_id=1, event_id=1)
        
        assert "no technical contact" in str(exc_info.value).lower()
    
    def test_missing_technical_phone_raises_error(self):
        """Test that missing technical phone raises ValueError."""
        # Mock event with technical contact but no phone
        mock_event = {
            "event_id": 1,
            "name": "Test Event",
            "technical_contact_id": 10,
            "technical_phone": "",
            "technical_name": "Tech Name",
        }
        self.service.get_event_with_contacts = MagicMock(return_value=mock_event)
        
        with pytest.raises(ValueError) as exc_info:
            self.service.build_tech_reminder_employee_payload(org_id=1, event_id=1)
        
        assert "no phone" in str(exc_info.value).lower()
    
    def test_no_shifts_raises_error(self):
        """Test that no assigned shifts raises ValueError."""
        # Mock event with technical contact
        mock_event = {
            "event_id": 1,
            "name": "Test Event",
            "event_date": datetime(2025, 12, 25).date(),
            "load_in_time": datetime(2025, 12, 25, 10, 0, tzinfo=timezone.utc),
            "show_time": datetime(2025, 12, 25, 20, 0, tzinfo=timezone.utc),
            "technical_contact_id": 10,
            "technical_phone": "0501234567",
            "technical_name": "Tech Name",
        }
        self.service.get_event_with_contacts = MagicMock(return_value=mock_event)
        self.service.employee_shifts.list_shifts_for_event = MagicMock(return_value=[])
        
        with pytest.raises(ValueError) as exc_info:
            self.service.build_tech_reminder_employee_payload(org_id=1, event_id=1)
        
        assert "no employees assigned" in str(exc_info.value).lower()
    
    def test_no_valid_call_times_raises_error(self):
        """Test that shifts without call_time raises ValueError."""
        # Mock event and shifts without call_time
        mock_event = {
            "event_id": 1,
            "name": "Test Event",
            "event_date": datetime(2025, 12, 25).date(),
            "load_in_time": datetime(2025, 12, 25, 10, 0, tzinfo=timezone.utc),
            "show_time": datetime(2025, 12, 25, 20, 0, tzinfo=timezone.utc),
            "technical_contact_id": 10,
            "technical_phone": "0501234567",
            "technical_name": "Tech Name",
        }
        mock_shifts = [
            {"shift_id": 1, "employee_name": "Employee 1", "call_time": None},
            {"shift_id": 2, "employee_name": "Employee 2", "call_time": None},
        ]
        
        self.service.get_event_with_contacts = MagicMock(return_value=mock_event)
        self.service.employee_shifts.list_shifts_for_event = MagicMock(return_value=mock_shifts)
        
        with pytest.raises(ValueError) as exc_info:
            self.service.build_tech_reminder_employee_payload(org_id=1, event_id=1)
        
        assert "cannot determine opening employee" in str(exc_info.value).lower()
    
    def test_successful_payload_build(self):
        """Test successful payload building with valid data."""
        # Mock complete event with shifts
        mock_event = {
            "event_id": 1,
            "name": "Test Concert",
            "event_date": datetime(2025, 12, 25).date(),
            "load_in_time": datetime(2025, 12, 25, 10, 0, tzinfo=timezone.utc),
            "show_time": datetime(2025, 12, 25, 20, 0, tzinfo=timezone.utc),
            "technical_contact_id": 10,
            "technical_phone": "0501234567",
            "technical_name": "David Cohen",
        }
        
        # Create shifts with different call times
        mock_shifts = [
            {
                "shift_id": 1,
                "employee_id": 100,
                "employee_name": "Sarah Levi",
                "employee_phone": "0509876543",
                "call_time": datetime(2025, 12, 25, 9, 0, tzinfo=timezone.utc),  # Earliest
            },
            {
                "shift_id": 2,
                "employee_id": 101,
                "employee_name": "Michael Israeli",
                "employee_phone": "0507654321",
                "call_time": datetime(2025, 12, 25, 10, 30, tzinfo=timezone.utc),
            },
        ]
        
        self.service.get_event_with_contacts = MagicMock(return_value=mock_event)
        self.service.employee_shifts.list_shifts_for_event = MagicMock(return_value=mock_shifts)
        
        # Build payload
        payload = self.service.build_tech_reminder_employee_payload(org_id=1, event_id=1)
        
        # Assertions
        assert payload is not None
        assert "to_phone" in payload
        assert "variables" in payload
        assert "opening_employee_metadata" in payload
        
        # Check to_phone format
        assert payload["to_phone"].startswith("whatsapp:+972")
        
        # Check variables structure
        variables = payload["variables"]
        assert len(variables) == 7
        assert "1" in variables  # Tech first name
        assert "2" in variables  # Event name
        assert "3" in variables  # Event date
        assert "4" in variables  # Load-in time
        assert "5" in variables  # Show time
        assert "6" in variables  # Employee first name
        assert "7" in variables  # Employee phone
        
        # Check variable values
        assert variables["1"] == "David"  # First name only
        assert variables["2"] == "Test Concert"
        assert variables["3"] == "25/12/2025"
        assert variables["6"] == "Sarah"  # First name only, earliest employee
        assert variables["7"].startswith("+972")  # E.164 format
        
        # Check metadata
        metadata = payload["opening_employee_metadata"]
        assert metadata["employee_id"] == 100
        assert metadata["employee_name"] == "Sarah Levi"
        assert metadata["shift_id"] == 1


class TestTemplateStructure:
    """Test the template JSON structure."""
    
    def test_template_file_exists(self):
        """Test that template file exists."""
        import os
        template_path = "twilio_templates/hoh_tech_reminder_employee_text_he_v1.json"
        assert os.path.exists(template_path)
    
    def test_template_json_valid(self):
        """Test that template JSON is valid and well-formed."""
        import json
        
        with open("twilio_templates/hoh_tech_reminder_employee_text_he_v1.json", "r", encoding="utf-8") as f:
            template = json.load(f)
        
        # Check required fields
        assert template["channel"] == "whatsapp"
        assert template["language"] == "he"
        assert template["category"] == "utility"
        assert template["type"] == "text"
        assert template["variables"] == ["1", "2", "3", "4", "5", "6", "7"]
        
        # Check body contains all variables
        body = template["body"]
        for i in range(1, 8):
            assert f"{{{{{i}}}}}" in body, f"Body must contain variable {{{{{i}}}}}"
        
        # Check Hebrew content
        assert "היי" in body
        assert "תזכורת" in body
        assert "כניסה להקמות" in body
        assert "תחילת מופע" in body


class TestCredentials:
    """Test credentials configuration."""
    
    def test_new_env_var_loaded(self):
        """Test that new env var is loaded in credentials."""
        from app import credentials
        
        assert hasattr(credentials, "CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT")
        assert credentials.CONTENT_SID_TECH_REMINDER_EMPLOYEE_TEXT == "HX_test_tech_reminder"
