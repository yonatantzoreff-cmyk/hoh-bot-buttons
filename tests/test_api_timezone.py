"""
Test that API endpoints return properly formatted Israel timezone values.
This ensures PHASE 0 requirement that all UI times are in Israel timezone.
"""
import os
from datetime import datetime, timezone

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

from app.time_utils import (
    utc_to_local_time_str,
    format_datetime_for_display,
)


def test_api_returns_israel_time_for_show_time():
    """
    Verify that when API receives UTC time from DB, it returns Israel local time.
    This is the core requirement: no more UTC-2 bug in the UI.
    """
    # Simulate a UTC datetime from database (18:00 UTC on July 15, 2024 - summer)
    utc_dt = datetime(2024, 7, 15, 18, 0, tzinfo=timezone.utc)
    
    # This is what the API should return in show_time_display field
    display_time = utc_to_local_time_str(utc_dt)
    
    # Should be 21:00 (Israel time in summer is UTC+3)
    assert display_time == "21:00", f"Expected 21:00 but got {display_time}"


def test_api_returns_israel_time_for_load_in_time():
    """
    Verify load_in_time is also displayed in Israel timezone.
    """
    # Winter time: 19:00 UTC on January 15, 2024
    utc_dt = datetime(2024, 1, 15, 19, 0, tzinfo=timezone.utc)
    
    # This is what the API should return in load_in_time_display field
    display_time = utc_to_local_time_str(utc_dt)
    
    # Should be 21:00 (Israel time in winter is UTC+2)
    assert display_time == "21:00", f"Expected 21:00 but got {display_time}"


def test_api_returns_full_datetime_with_israel_time():
    """
    Verify that full datetime formatting (used for tooltips) shows Israel time.
    """
    # Summer: 15:30 UTC on August 10, 2024
    utc_dt = datetime(2024, 8, 10, 15, 30, tzinfo=timezone.utc)
    
    # This is what the API should return in init_sent_at_display field
    display_datetime = format_datetime_for_display(utc_dt)
    
    # Should be 18:30 Israel time (UTC+3 in summer)
    # Format is "DD/MM/YYYY HH:MM"
    assert "18:30" in display_datetime, f"Expected time 18:30 but got {display_datetime}"
    assert "10/08/2024" in display_datetime, f"Expected date 10/08/2024 but got {display_datetime}"


def test_no_utc_minus_two_hours_bug():
    """
    This is the explicit test for the UTC-2 bug.
    
    The bug was: user sets 21:00 Israel time, but UI shows 19:00 (21:00 - 2 hours).
    This should NEVER happen.
    """
    # User wants to display 21:00
    # In summer, this is stored as 18:00 UTC in DB
    utc_stored = datetime(2024, 7, 15, 18, 0, tzinfo=timezone.utc)
    
    # When we display it, it should be 21:00, NOT 19:00
    displayed = utc_to_local_time_str(utc_stored)
    
    assert displayed == "21:00", f"UTC-2 bug detected! Expected 21:00 but got {displayed}"
    assert displayed != "19:00", "CRITICAL: UTC-2 bug is back! Time is off by 2 hours!"
    
    # Also test winter time
    utc_stored_winter = datetime(2024, 1, 15, 19, 0, tzinfo=timezone.utc)
    displayed_winter = utc_to_local_time_str(utc_stored_winter)
    
    assert displayed_winter == "21:00", f"Winter: Expected 21:00 but got {displayed_winter}"
    assert displayed_winter != "19:00", "CRITICAL: UTC-2 bug in winter!"


def test_shift_times_are_israel_timezone():
    """
    Verify that shift call times are also displayed in Israel timezone.
    """
    # Shift scheduled for 09:00 Israel time on June 20, 2024 (summer)
    # This is stored as 06:00 UTC
    utc_dt = datetime(2024, 6, 20, 6, 0, tzinfo=timezone.utc)
    
    display_time = utc_to_local_time_str(utc_dt)
    
    assert display_time == "09:00", f"Shift time: Expected 09:00 but got {display_time}"
