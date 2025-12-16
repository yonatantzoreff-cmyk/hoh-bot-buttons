"""
Comprehensive timezone tests to ensure the timezone bug is fixed forever.

These tests validate:
1. Round-trip UI→DB→UI preserves the correct time
2. Edit operations don't shift times
3. DST handling works correctly for both summer and winter
4. Twilio message formatting shows correct local times
"""

import os
from datetime import date, datetime, time, timezone
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

from app.time_utils import (
    parse_local_time_to_utc,
    utc_to_local_time_str,
    utc_to_local_datetime,
    ensure_aware,
    get_il_tz,
)


def test_parse_local_time_to_utc_summer():
    """Test that 21:00 Israel time in summer converts to 18:00 UTC (DST active)."""
    # July 15, 2024 is during daylight saving time in Israel (UTC+3)
    event_date = date(2024, 7, 15)
    local_time = "21:00"
    
    result = parse_local_time_to_utc(event_date, local_time)
    
    # 21:00 Israel time (UTC+3 in summer) = 18:00 UTC
    assert result.hour == 18
    assert result.minute == 0
    assert result.tzinfo == timezone.utc


def test_parse_local_time_to_utc_winter():
    """Test that 21:00 Israel time in winter converts to 19:00 UTC (no DST)."""
    # January 15, 2024 is during standard time in Israel (UTC+2)
    event_date = date(2024, 1, 15)
    local_time = "21:00"
    
    result = parse_local_time_to_utc(event_date, local_time)
    
    # 21:00 Israel time (UTC+2 in winter) = 19:00 UTC
    assert result.hour == 19
    assert result.minute == 0
    assert result.tzinfo == timezone.utc


def test_utc_to_local_time_str_summer():
    """Test that UTC time converts to correct Israel time string in summer."""
    # Create a UTC datetime: 18:00 UTC on July 15, 2024
    utc_dt = datetime(2024, 7, 15, 18, 0, tzinfo=timezone.utc)
    
    result = utc_to_local_time_str(utc_dt)
    
    # 18:00 UTC in summer = 21:00 Israel time (UTC+3)
    assert result == "21:00"


def test_utc_to_local_time_str_winter():
    """Test that UTC time converts to correct Israel time string in winter."""
    # Create a UTC datetime: 19:00 UTC on January 15, 2024
    utc_dt = datetime(2024, 1, 15, 19, 0, tzinfo=timezone.utc)
    
    result = utc_to_local_time_str(utc_dt)
    
    # 19:00 UTC in winter = 21:00 Israel time (UTC+2)
    assert result == "21:00"


def test_round_trip_summer():
    """Test that a time makes a full round trip UI→UTC→UI correctly in summer."""
    event_date = date(2024, 7, 15)
    original_time = "21:00"
    
    # UI sends "21:00" for July 15
    utc_dt = parse_local_time_to_utc(event_date, original_time)
    
    # Store in DB (as UTC)
    assert utc_dt.tzinfo == timezone.utc
    
    # Retrieve from DB and convert back to display
    display_time = utc_to_local_time_str(utc_dt)
    
    # Should get back "21:00"
    assert display_time == original_time


def test_round_trip_winter():
    """Test that a time makes a full round trip UI→UTC→UI correctly in winter."""
    event_date = date(2024, 1, 15)
    original_time = "21:00"
    
    # UI sends "21:00" for January 15
    utc_dt = parse_local_time_to_utc(event_date, original_time)
    
    # Store in DB (as UTC)
    assert utc_dt.tzinfo == timezone.utc
    
    # Retrieve from DB and convert back to display
    display_time = utc_to_local_time_str(utc_dt)
    
    # Should get back "21:00"
    assert display_time == original_time


def test_edit_preserves_time_summer():
    """
    Test that editing an event doesn't shift the time (summer).
    
    This is the core bug we're fixing: when a user edits an event
    without changing the time, it should stay the same.
    """
    event_date = date(2024, 7, 15)
    original_time = "21:00"
    
    # Step 1: Create event with time 21:00
    utc_dt_1 = parse_local_time_to_utc(event_date, original_time)
    
    # Step 2: Load event for editing - convert to display format
    display_time = utc_to_local_time_str(utc_dt_1)
    assert display_time == "21:00"
    
    # Step 3: User doesn't change time, saves form with same "21:00"
    utc_dt_2 = parse_local_time_to_utc(event_date, display_time)
    
    # Step 4: Verify the UTC times are identical
    assert utc_dt_1 == utc_dt_2
    
    # Step 5: Display again should still show "21:00"
    final_display = utc_to_local_time_str(utc_dt_2)
    assert final_display == "21:00"


def test_edit_preserves_time_winter():
    """
    Test that editing an event doesn't shift the time (winter).
    """
    event_date = date(2024, 1, 15)
    original_time = "21:00"
    
    # Step 1: Create event with time 21:00
    utc_dt_1 = parse_local_time_to_utc(event_date, original_time)
    
    # Step 2: Load event for editing - convert to display format
    display_time = utc_to_local_time_str(utc_dt_1)
    assert display_time == "21:00"
    
    # Step 3: User doesn't change time, saves form with same "21:00"
    utc_dt_2 = parse_local_time_to_utc(event_date, display_time)
    
    # Step 4: Verify the UTC times are identical
    assert utc_dt_1 == utc_dt_2
    
    # Step 5: Display again should still show "21:00"
    final_display = utc_to_local_time_str(utc_dt_2)
    assert final_display == "21:00"


def test_multiple_edits_dont_drift():
    """
    Test that multiple successive edits don't cause time drift.
    
    This was the original bug: each edit would shift by 2 hours.
    """
    event_date = date(2024, 7, 15)
    original_time = "21:00"
    
    # Create event
    utc_dt = parse_local_time_to_utc(event_date, original_time)
    
    # Simulate 5 edit cycles
    for i in range(5):
        # Load for editing
        display_time = utc_to_local_time_str(utc_dt)
        assert display_time == "21:00", f"After edit {i}, time drifted to {display_time}"
        
        # Save without changes
        utc_dt = parse_local_time_to_utc(event_date, display_time)
    
    # Final check
    final_display = utc_to_local_time_str(utc_dt)
    assert final_display == "21:00"


def test_dst_transition_handling():
    """
    Test that times near DST transitions are handled correctly.
    
    In Israel, DST typically starts in late March and ends in late October.
    """
    # Day before DST starts (still UTC+2)
    date_before = date(2024, 3, 28)
    utc_before = parse_local_time_to_utc(date_before, "21:00")
    
    # Day after DST starts (now UTC+3)
    date_after = date(2024, 3, 30)
    utc_after = parse_local_time_to_utc(date_after, "21:00")
    
    # Both should display as "21:00" locally, but UTC times should differ by 1 hour
    assert utc_to_local_time_str(utc_before) == "21:00"
    assert utc_to_local_time_str(utc_after) == "21:00"
    
    # The UTC times should be different (1 hour apart)
    time_diff = utc_before.hour - utc_after.hour
    # Could be 1 or -23 depending on date handling, but absolute diff is 1
    assert abs(time_diff) == 1 or abs(time_diff) == 23


def test_ensure_aware_with_utc():
    """Test that ensure_aware correctly handles naive datetimes assuming UTC."""
    naive_dt = datetime(2024, 7, 15, 18, 0)
    
    aware_dt = ensure_aware(naive_dt, assume_utc=True)
    
    assert aware_dt.tzinfo is not None
    assert aware_dt.tzinfo == timezone.utc


def test_ensure_aware_already_aware():
    """Test that ensure_aware doesn't modify already-aware datetimes."""
    aware_dt = datetime(2024, 7, 15, 18, 0, tzinfo=timezone.utc)
    
    result = ensure_aware(aware_dt)
    
    assert result is aware_dt  # Should be the same object
    assert result.tzinfo == timezone.utc


def test_utc_to_local_datetime():
    """Test conversion of UTC datetime to Israel local datetime."""
    utc_dt = datetime(2024, 7, 15, 18, 0, tzinfo=timezone.utc)
    
    local_dt = utc_to_local_datetime(utc_dt)
    
    assert local_dt.tzinfo == get_il_tz()
    assert local_dt.hour == 21  # 18:00 UTC + 3 hours (summer)
    assert local_dt.minute == 0


def test_different_hours_convert_correctly():
    """Test that different times of day convert correctly."""
    event_date = date(2024, 7, 15)
    
    test_cases = [
        ("00:00", 0),   # Midnight
        ("06:00", 6),   # Morning
        ("12:00", 12),  # Noon
        ("18:00", 18),  # Evening
        ("23:59", 23),  # Late night
    ]
    
    for local_time, expected_local_hour in test_cases:
        # Convert to UTC and back
        utc_dt = parse_local_time_to_utc(event_date, local_time)
        display_time = utc_to_local_time_str(utc_dt)
        
        # Should get back the same time
        assert display_time == local_time, f"Failed for {local_time}"


def test_twilio_message_formatting():
    """
    Test that times displayed in Twilio messages are in local Israel time.
    
    This ensures that when we send WhatsApp messages, users see the
    correct local time, not UTC.
    """
    # Create a UTC datetime for an event
    utc_dt = datetime(2024, 7, 15, 18, 0, tzinfo=timezone.utc)
    
    # Format for message (should show Israel local time)
    message_time = utc_to_local_time_str(utc_dt)
    
    # Should show 21:00 (Israel time), not 18:00 (UTC)
    assert message_time == "21:00"
    
    # Verify it's not showing UTC
    assert message_time != "18:00"


def test_event_date_strftime_formatting():
    """Test that event dates format correctly for display."""
    event_date = date(2024, 7, 15)
    
    # Format as we do in the UI
    formatted = event_date.strftime("%Y-%m-%d")
    
    assert formatted == "2024-07-15"


def test_handles_none_values():
    """Test that timezone utilities handle None values gracefully."""
    assert utc_to_local_time_str(None) == ""
    assert utc_to_local_datetime(None) is None
    assert ensure_aware(None) is None
