"""
Unit tests for shift generation logic.
"""

import pytest
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from app.services.shift_generator import (
    create_slots_for_event,
    is_weekend_shift,
    is_night_shift,
    is_morning_shift,
    violates_night_to_morning_rule,
    has_sufficient_rest,
    has_availability_conflict,
    worked_yesterday,
    count_weekend_shifts,
    MAX_SHIFT_HOURS,
    DEFAULT_SHIFT_HOURS,
)

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def test_create_slots_short_event():
    """Test slot creation for event shorter than 12 hours."""
    event = {
        "event_id": 1,
        "event_date": date(2025, 1, 15),
        "load_in_time": time(18, 0),
        "show_time": time(21, 0),
    }
    
    slots = create_slots_for_event(event)
    
    # Should create 1 slot (21:00 + 5h buffer = 02:00 next day, total 8 hours)
    assert len(slots) == 1
    assert slots[0]["event_id"] == 1
    
    start = slots[0]["start_at"]
    end = slots[0]["end_at"]
    
    duration = (end - start).total_seconds() / 3600
    assert duration <= MAX_SHIFT_HOURS


def test_create_slots_long_event():
    """Test slot creation for event longer than 12 hours."""
    event = {
        "event_id": 2,
        "event_date": date(2025, 1, 15),
        "load_in_time": time(10, 0),
        "show_time": time(22, 0),  # With 5h buffer = 03:00 next day (17 hours total)
    }
    
    slots = create_slots_for_event(event)
    
    # Should create multiple slots
    assert len(slots) >= 2
    
    # Each slot should be <= 12 hours
    for slot in slots:
        duration = (slot["end_at"] - slot["start_at"]).total_seconds() / 3600
        assert duration <= MAX_SHIFT_HOURS
    
    # First slot should start at load_in_time
    assert slots[0]["start_at"].time() == time(10, 0)
    
    # Last slot should end at show_time + 5h
    expected_end = datetime.combine(date(2025, 1, 16), time(3, 0)).replace(tzinfo=ISRAEL_TZ)
    assert slots[-1]["end_at"] == expected_end


def test_is_weekend_shift():
    """Test weekend shift detection."""
    # Friday 16:00 - weekend
    friday_afternoon = datetime(2025, 1, 17, 16, 0, tzinfo=ISRAEL_TZ)  # Friday
    assert is_weekend_shift(friday_afternoon) is True
    
    # Friday 14:00 - not weekend yet
    friday_morning = datetime(2025, 1, 17, 14, 0, tzinfo=ISRAEL_TZ)
    assert is_weekend_shift(friday_morning) is False
    
    # Saturday 18:00 - weekend
    saturday = datetime(2025, 1, 18, 18, 0, tzinfo=ISRAEL_TZ)  # Saturday
    assert is_weekend_shift(saturday) is True
    
    # Sunday 10:00 - not weekend
    sunday = datetime(2025, 1, 19, 10, 0, tzinfo=ISRAEL_TZ)
    assert is_weekend_shift(sunday) is False


def test_is_night_shift():
    """Test night shift detection."""
    # Shift from 22:00 to 06:00 - night shift
    night_start = datetime(2025, 1, 15, 22, 0, tzinfo=ISRAEL_TZ)
    night_end = datetime(2025, 1, 16, 6, 0, tzinfo=ISRAEL_TZ)
    assert is_night_shift(night_start, night_end) is True
    
    # Shift from 20:00 to 02:00 - touches night
    evening_start = datetime(2025, 1, 15, 20, 0, tzinfo=ISRAEL_TZ)
    early_morning = datetime(2025, 1, 16, 2, 0, tzinfo=ISRAEL_TZ)
    assert is_night_shift(evening_start, early_morning) is True
    
    # Shift from 10:00 to 18:00 - not night
    day_start = datetime(2025, 1, 15, 10, 0, tzinfo=ISRAEL_TZ)
    day_end = datetime(2025, 1, 15, 18, 0, tzinfo=ISRAEL_TZ)
    assert is_night_shift(day_start, day_end) is False


def test_is_morning_shift():
    """Test morning shift detection."""
    # 07:00 start - morning
    morning = datetime(2025, 1, 15, 7, 0, tzinfo=ISRAEL_TZ)
    assert is_morning_shift(morning) is True
    
    # 13:00 start - not morning
    afternoon = datetime(2025, 1, 15, 13, 0, tzinfo=ISRAEL_TZ)
    assert is_morning_shift(afternoon) is False


def test_violates_night_to_morning_rule():
    """Test night->morning rule enforcement."""
    # Employee worked night shift on Jan 15
    night_shift = {
        "start_at": datetime(2025, 1, 15, 22, 0, tzinfo=ISRAEL_TZ),
        "end_at": datetime(2025, 1, 16, 6, 0, tzinfo=ISRAEL_TZ),
        "employee_id": 1,
    }
    
    employee_shifts = [night_shift]
    
    # Try to assign morning shift on Jan 16 - should violate
    morning_slot = datetime(2025, 1, 16, 8, 0, tzinfo=ISRAEL_TZ)
    assert violates_night_to_morning_rule(employee_shifts, morning_slot) is True
    
    # Try to assign afternoon shift on Jan 16 - should be OK
    afternoon_slot = datetime(2025, 1, 16, 14, 0, tzinfo=ISRAEL_TZ)
    assert violates_night_to_morning_rule(employee_shifts, afternoon_slot) is False
    
    # Try to assign morning shift on Jan 17 - should be OK (different day)
    next_morning_slot = datetime(2025, 1, 17, 8, 0, tzinfo=ISRAEL_TZ)
    assert violates_night_to_morning_rule(employee_shifts, next_morning_slot) is False


def test_has_sufficient_rest():
    """Test 10-hour rest rule."""
    # Previous shift ended at 22:00
    previous_shift = {
        "start_at": datetime(2025, 1, 15, 14, 0, tzinfo=ISRAEL_TZ),
        "end_at": datetime(2025, 1, 15, 22, 0, tzinfo=ISRAEL_TZ),
        "employee_id": 1,
    }
    
    employee_shifts = [previous_shift]
    
    # New slot at 06:00 next day (8 hours rest) - insufficient
    insufficient_rest_slot = datetime(2025, 1, 16, 6, 0, tzinfo=ISRAEL_TZ)
    assert has_sufficient_rest(employee_shifts, insufficient_rest_slot) is False
    
    # New slot at 09:00 next day (11 hours rest) - sufficient
    sufficient_rest_slot = datetime(2025, 1, 16, 9, 0, tzinfo=ISRAEL_TZ)
    assert has_sufficient_rest(employee_shifts, sufficient_rest_slot) is True


def test_has_availability_conflict():
    """Test unavailability conflict detection."""
    unavailability = [
        {
            "start_at": datetime(2025, 1, 15, 10, 0, tzinfo=ISRAEL_TZ),
            "end_at": datetime(2025, 1, 15, 18, 0, tzinfo=ISRAEL_TZ),
            "employee_id": 1,
        }
    ]
    
    # Slot overlaps with unavailability
    overlapping_slot_start = datetime(2025, 1, 15, 16, 0, tzinfo=ISRAEL_TZ)
    overlapping_slot_end = datetime(2025, 1, 15, 20, 0, tzinfo=ISRAEL_TZ)
    assert has_availability_conflict(unavailability, overlapping_slot_start, overlapping_slot_end) is True
    
    # Slot before unavailability
    before_slot_start = datetime(2025, 1, 15, 8, 0, tzinfo=ISRAEL_TZ)
    before_slot_end = datetime(2025, 1, 15, 10, 0, tzinfo=ISRAEL_TZ)
    assert has_availability_conflict(unavailability, before_slot_start, before_slot_end) is False
    
    # Slot after unavailability
    after_slot_start = datetime(2025, 1, 15, 18, 0, tzinfo=ISRAEL_TZ)
    after_slot_end = datetime(2025, 1, 15, 22, 0, tzinfo=ISRAEL_TZ)
    assert has_availability_conflict(unavailability, after_slot_start, after_slot_end) is False


def test_worked_yesterday():
    """Test yesterday work detection."""
    # Shift on Jan 15
    shift = {
        "start_at": datetime(2025, 1, 15, 14, 0, tzinfo=ISRAEL_TZ),
        "call_time": datetime(2025, 1, 15, 14, 0, tzinfo=ISRAEL_TZ),
        "employee_id": 1,
    }
    
    employee_shifts = [shift]
    
    # Check on Jan 16 - should return True
    slot_date = datetime(2025, 1, 16, 10, 0, tzinfo=ISRAEL_TZ)
    assert worked_yesterday(employee_shifts, slot_date) is True
    
    # Check on Jan 17 - should return False
    slot_date2 = datetime(2025, 1, 17, 10, 0, tzinfo=ISRAEL_TZ)
    assert worked_yesterday(employee_shifts, slot_date2) is False


def test_count_weekend_shifts():
    """Test weekend shift counting."""
    shifts = [
        # Friday afternoon - weekend
        {
            "start_at": datetime(2025, 1, 17, 16, 0, tzinfo=ISRAEL_TZ),
            "call_time": datetime(2025, 1, 17, 16, 0, tzinfo=ISRAEL_TZ),
        },
        # Saturday - weekend
        {
            "start_at": datetime(2025, 1, 18, 18, 0, tzinfo=ISRAEL_TZ),
            "call_time": datetime(2025, 1, 18, 18, 0, tzinfo=ISRAEL_TZ),
        },
        # Sunday - not weekend
        {
            "start_at": datetime(2025, 1, 19, 10, 0, tzinfo=ISRAEL_TZ),
            "call_time": datetime(2025, 1, 19, 10, 0, tzinfo=ISRAEL_TZ),
        },
    ]
    
    assert count_weekend_shifts(shifts) == 2
