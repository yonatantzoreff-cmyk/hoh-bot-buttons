"""
Tests for compute_send_at helper function.

This function is used for scheduling messages with weekend rule support.
Weekend rule applies ONLY for INIT messages - TECH_REMINDER and SHIFT_REMINDER
can be sent on Friday/Saturday.
"""

import os
from datetime import date, datetime, time, timedelta, timezone
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
    compute_send_at,
    parse_local_time_to_utc,
    utc_to_local_datetime,
    get_il_tz,
    now_utc,
)


def test_compute_send_at_regular_weekday():
    """Test compute_send_at on a regular weekday (no weekend rule applied)."""
    # Event on Thursday, July 18, 2024
    event_date = date(2024, 7, 18)
    fixed_time = "09:00"
    days_before = 3
    
    # Current time: Monday, July 8, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 8), "10:00")
    
    # Should schedule for Monday, July 15, 2024 at 09:00
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 15)
    assert result_israel.hour == 9
    assert result_israel.minute == 0
    assert result_israel.weekday() == 0  # Monday


def test_compute_send_at_past_date_moves_to_tomorrow():
    """Test that if candidate is in the past, it moves to tomorrow."""
    # Event on Thursday, July 18, 2024
    event_date = date(2024, 7, 18)
    fixed_time = "09:00"
    days_before = 3
    
    # Current time: Tuesday, July 16, 2024 at 10:00 Israel time
    # Candidate would be Monday July 15 at 09:00, which is in the past
    now = parse_local_time_to_utc(date(2024, 7, 16), "10:00")
    
    # Should move to tomorrow (Wednesday, July 17) at 09:00
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 17)
    assert result_israel.hour == 9
    assert result_israel.minute == 0
    assert result_israel.weekday() == 2  # Wednesday


def test_compute_send_at_init_on_friday_moves_to_sunday():
    """Test INIT message scheduled for Friday moves to Sunday with weekend rule."""
    # Event on Saturday, July 20, 2024
    event_date = date(2024, 7, 20)
    fixed_time = "09:00"
    days_before = 1
    
    # Current time: Wednesday, July 17, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 17), "10:00")
    
    # Without weekend rule, would be Friday July 19
    # With weekend rule, should move to Sunday July 21
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=True)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 21)
    assert result_israel.hour == 9
    assert result_israel.minute == 0
    assert result_israel.weekday() == 6  # Sunday


def test_compute_send_at_init_on_saturday_moves_to_sunday():
    """Test INIT message scheduled for Saturday moves to Sunday with weekend rule."""
    # Event on Sunday, July 21, 2024
    event_date = date(2024, 7, 21)
    fixed_time = "09:00"
    days_before = 1
    
    # Current time: Thursday, July 18, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 18), "10:00")
    
    # Without weekend rule, would be Saturday July 20
    # With weekend rule, should move to Sunday July 21
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=True)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 21)
    assert result_israel.hour == 9
    assert result_israel.minute == 0
    assert result_israel.weekday() == 6  # Sunday


def test_compute_send_at_tech_reminder_on_friday_unchanged():
    """Test TECH_REMINDER on Friday stays on Friday (no weekend rule)."""
    # Event on Saturday, July 20, 2024
    event_date = date(2024, 7, 20)
    fixed_time = "09:00"
    days_before = 1
    
    # Current time: Wednesday, July 17, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 17), "10:00")
    
    # Without weekend rule, should stay on Friday July 19
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 19)
    assert result_israel.hour == 9
    assert result_israel.minute == 0
    assert result_israel.weekday() == 4  # Friday


def test_compute_send_at_shift_reminder_on_saturday_unchanged():
    """Test SHIFT_REMINDER on Saturday stays on Saturday (no weekend rule)."""
    # Event on Sunday, July 21, 2024
    event_date = date(2024, 7, 21)
    fixed_time = "09:00"
    days_before = 1
    
    # Current time: Thursday, July 18, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 18), "10:00")
    
    # Without weekend rule, should stay on Saturday July 20
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 20)
    assert result_israel.hour == 9
    assert result_israel.minute == 0
    assert result_israel.weekday() == 5  # Saturday


def test_compute_send_at_dst_summer():
    """Test compute_send_at handles DST correctly in summer (UTC+3)."""
    # Event on Thursday, July 18, 2024 (DST active)
    event_date = date(2024, 7, 18)
    fixed_time = "21:00"
    days_before = 3
    
    # Current time: Monday, July 8, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 8), "10:00")
    
    # Should schedule for Monday, July 15, 2024 at 21:00 Israel time
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Verify it's timezone-aware and in UTC
    assert result.tzinfo == timezone.utc
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 15)
    assert result_israel.hour == 21
    assert result_israel.minute == 0
    
    # In summer, 21:00 Israel time = 18:00 UTC (UTC+3)
    assert result.hour == 18


def test_compute_send_at_dst_winter():
    """Test compute_send_at handles DST correctly in winter (UTC+2)."""
    # Event on Thursday, January 18, 2024 (no DST)
    event_date = date(2024, 1, 18)
    fixed_time = "21:00"
    days_before = 3
    
    # Current time: Monday, January 8, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 1, 8), "10:00")
    
    # Should schedule for Monday, January 15, 2024 at 21:00 Israel time
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Verify it's timezone-aware and in UTC
    assert result.tzinfo == timezone.utc
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 1, 15)
    assert result_israel.hour == 21
    assert result_israel.minute == 0
    
    # In winter, 21:00 Israel time = 19:00 UTC (UTC+2)
    assert result.hour == 19


def test_compute_send_at_with_naive_now_datetime():
    """Test that compute_send_at handles naive 'now' datetime gracefully."""
    # Event on Thursday, July 18, 2024
    event_date = date(2024, 7, 18)
    fixed_time = "09:00"
    days_before = 3
    
    # Current time: Monday, July 8, 2024 at 07:00 UTC (naive datetime)
    # This is treated as UTC by the function, which is 10:00 Israel time in summer (UTC+3)
    now_naive = datetime(2024, 7, 8, 7, 0)
    
    # Should still work, treating naive as UTC
    result = compute_send_at(event_date, fixed_time, days_before, now_naive, apply_weekend_rule=False)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 15)
    assert result_israel.hour == 9


def test_compute_send_at_different_times():
    """Test compute_send_at with different times of day."""
    # Event on Thursday, July 18, 2024
    event_date = date(2024, 7, 18)
    days_before = 3
    
    # Current time: Monday, July 8, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 8), "10:00")
    
    test_cases = [
        ("00:00", 0, 0),   # Midnight
        ("06:00", 6, 0),   # Morning
        ("12:00", 12, 0),  # Noon
        ("18:00", 18, 0),  # Evening
        ("23:30", 23, 30), # Late night with minutes
    ]
    
    for fixed_time, expected_hour, expected_minute in test_cases:
        result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
        result_israel = utc_to_local_datetime(result)
        
        assert result_israel.date() == date(2024, 7, 15), f"Failed for time {fixed_time}"
        assert result_israel.hour == expected_hour, f"Failed hour for time {fixed_time}"
        assert result_israel.minute == expected_minute, f"Failed minute for time {fixed_time}"


def test_compute_send_at_zero_days_before():
    """Test compute_send_at with zero days before (same day as event)."""
    # Event on Thursday, July 18, 2024
    event_date = date(2024, 7, 18)
    fixed_time = "09:00"
    days_before = 0
    
    # Current time: Monday, July 8, 2024 at 10:00 Israel time
    now = parse_local_time_to_utc(date(2024, 7, 8), "10:00")
    
    # Should schedule for the event date itself (Thursday, July 18)
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 18)
    assert result_israel.hour == 9
    assert result_israel.minute == 0


def test_compute_send_at_returns_utc():
    """Test that compute_send_at always returns timezone-aware UTC datetime."""
    # Event on Thursday, July 18, 2024
    event_date = date(2024, 7, 18)
    fixed_time = "09:00"
    days_before = 3
    now = now_utc()
    
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=False)
    
    # Must be timezone-aware
    assert result.tzinfo is not None
    # Must be in UTC
    assert result.tzinfo == timezone.utc


def test_compute_send_at_past_with_weekend_rule():
    """Test past date moves to tomorrow, then applies weekend rule if tomorrow is weekend."""
    # Event on Monday, July 22, 2024
    event_date = date(2024, 7, 22)
    fixed_time = "09:00"
    days_before = 5
    
    # Current time: Thursday, July 18, 2024 at 10:00 Israel time
    # Candidate would be Wednesday July 17 at 09:00, which is in the past
    # Tomorrow is Friday July 19, with weekend rule should move to Sunday July 21
    now = parse_local_time_to_utc(date(2024, 7, 18), "10:00")
    
    result = compute_send_at(event_date, fixed_time, days_before, now, apply_weekend_rule=True)
    
    # Convert to Israel time to check
    result_israel = utc_to_local_datetime(result)
    assert result_israel.date() == date(2024, 7, 21)
    assert result_israel.hour == 9
    assert result_israel.minute == 0
    assert result_israel.weekday() == 6  # Sunday
