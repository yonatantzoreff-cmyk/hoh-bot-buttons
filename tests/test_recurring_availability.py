"""
Tests for recurring availability rule expansion.

Tests weekly, biweekly, and monthly pattern expansion with:
- Correct date calculations
- Timezone handling (Asia/Jerusalem)
- Exception handling
- Precedence logic
"""

import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

# Set up test environment
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest

from app.services.recurring_availability import (
    expand_rule_for_month,
    merge_unavailability,
    check_event_conflicts,
)


ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def test_expand_weekly_rule():
    """Test weekly pattern expansion for a month."""
    # Rule: Every Sunday and Wednesday, all day
    rule = {
        "rule_id": 1,
        "pattern": "weekly",
        "days_of_week": [0, 3],  # Sunday=0, Wednesday=3
        "start_date": date(2025, 1, 1),
        "until_date": None,
        "all_day": True,
        "notes": "Weekly unavailability",
    }
    
    # Expand for January 2025
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=[])
    
    # January 2025: Sundays are 5, 12, 19, 26; Wednesdays are 1, 8, 15, 22, 29
    expected_dates = [
        date(2025, 1, 1),   # Wednesday
        date(2025, 1, 5),   # Sunday
        date(2025, 1, 8),   # Wednesday
        date(2025, 1, 12),  # Sunday
        date(2025, 1, 15),  # Wednesday
        date(2025, 1, 19),  # Sunday
        date(2025, 1, 22),  # Wednesday
        date(2025, 1, 26),  # Sunday
        date(2025, 1, 29),  # Wednesday
    ]
    
    actual_dates = [occ["date"] for occ in occurrences]
    assert actual_dates == expected_dates
    
    # Check that occurrences are all day
    for occ in occurrences:
        assert occ["start_at"].hour == 0
        assert occ["start_at"].minute == 0
        assert occ["end_at"].hour == 23
        assert occ["end_at"].minute == 59


def test_expand_weekly_rule_with_partial_hours():
    """Test weekly pattern with specific start/end times."""
    rule = {
        "rule_id": 2,
        "pattern": "weekly",
        "days_of_week": [1],  # Monday only
        "start_date": date(2025, 1, 1),
        "until_date": None,
        "all_day": False,
        "start_time": time(9, 0),
        "end_time": time(17, 0),
        "notes": "Monday 9-5",
    }
    
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=[])
    
    # January 2025 Mondays: 6, 13, 20, 27
    expected_dates = [
        date(2025, 1, 6),
        date(2025, 1, 13),
        date(2025, 1, 20),
        date(2025, 1, 27),
    ]
    
    actual_dates = [occ["date"] for occ in occurrences]
    assert actual_dates == expected_dates
    
    # Check times
    for occ in occurrences:
        assert occ["start_at"].hour == 9
        assert occ["start_at"].minute == 0
        assert occ["end_at"].hour == 17
        assert occ["end_at"].minute == 0


def test_expand_biweekly_rule():
    """Test biweekly pattern expansion."""
    # Rule: Every other Thursday, starting from Jan 2, 2025
    anchor_date = date(2025, 1, 2)  # Thursday
    rule = {
        "rule_id": 3,
        "pattern": "biweekly",
        "days_of_week": [4],  # Thursday=4
        "anchor_date": anchor_date,
        "start_date": anchor_date,
        "until_date": None,
        "all_day": True,
        "notes": "Biweekly Thursday",
    }
    
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=[])
    
    # Starting from Jan 2 (week 0), biweekly means Jan 2, Jan 16, Jan 30
    expected_dates = [
        date(2025, 1, 2),   # Week 0
        date(2025, 1, 16),  # Week 2
        date(2025, 1, 30),  # Week 4
    ]
    
    actual_dates = [occ["date"] for occ in occurrences]
    assert actual_dates == expected_dates


def test_expand_monthly_rule():
    """Test monthly pattern expansion."""
    # Rule: 15th of every month
    rule = {
        "rule_id": 4,
        "pattern": "monthly",
        "day_of_month": 15,
        "start_date": date(2025, 1, 1),
        "until_date": None,
        "all_day": True,
        "notes": "15th of month",
    }
    
    # Expand for January
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=[])
    
    expected_dates = [date(2025, 1, 15)]
    actual_dates = [occ["date"] for occ in occurrences]
    assert actual_dates == expected_dates


def test_expand_monthly_rule_invalid_day():
    """Test monthly pattern with day that doesn't exist in month (e.g., 31st in February)."""
    # Rule: 31st of every month
    rule = {
        "rule_id": 5,
        "pattern": "monthly",
        "day_of_month": 31,
        "start_date": date(2025, 1, 1),
        "until_date": None,
        "all_day": True,
        "notes": "31st of month",
    }
    
    # Expand for February 2025 (28 days, not a leap year)
    occurrences = expand_rule_for_month(rule, 2025, 2, exceptions=[])
    
    # Should be empty - February doesn't have 31 days
    assert occurrences == []
    
    # Expand for January (31 days)
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=[])
    assert len(occurrences) == 1
    assert occurrences[0]["date"] == date(2025, 1, 31)


def test_expand_rule_with_exceptions():
    """Test that exceptions properly cancel occurrences."""
    rule = {
        "rule_id": 6,
        "pattern": "weekly",
        "days_of_week": [1, 3],  # Monday and Wednesday
        "start_date": date(2025, 1, 1),
        "until_date": None,
        "all_day": True,
        "notes": "Weekly with exceptions",
    }
    
    # Add exceptions for some dates
    exceptions = [
        date(2025, 1, 6),   # Skip first Monday
        date(2025, 1, 15),  # Skip third Wednesday
    ]
    
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=exceptions)
    actual_dates = [occ["date"] for occ in occurrences]
    
    # Should not include the exception dates
    assert date(2025, 1, 6) not in actual_dates
    assert date(2025, 1, 15) not in actual_dates
    
    # But should include other Mondays and Wednesdays
    assert date(2025, 1, 1) in actual_dates   # Wednesday
    assert date(2025, 1, 8) in actual_dates   # Wednesday
    assert date(2025, 1, 13) in actual_dates  # Monday


def test_expand_rule_with_until_date():
    """Test that rule respects until_date boundary."""
    rule = {
        "rule_id": 7,
        "pattern": "weekly",
        "days_of_week": [1],  # Monday
        "start_date": date(2025, 1, 1),
        "until_date": date(2025, 1, 15),  # Ends mid-month
        "all_day": True,
        "notes": "Limited duration",
    }
    
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=[])
    actual_dates = [occ["date"] for occ in occurrences]
    
    # Should only include Mondays up to Jan 15
    assert date(2025, 1, 6) in actual_dates   # Monday
    assert date(2025, 1, 13) in actual_dates  # Monday
    assert date(2025, 1, 20) not in actual_dates  # After until_date
    assert date(2025, 1, 27) not in actual_dates  # After until_date


def test_merge_unavailability_manual_precedence():
    """Test that manual entries take precedence over rule entries on same date."""
    manual_entries = [
        {
            "unavailability_id": 1,
            "employee_id": 1,
            "start_at": datetime(2025, 1, 6, 8, 0, tzinfo=ISRAEL_TZ),
            "end_at": datetime(2025, 1, 6, 12, 0, tzinfo=ISRAEL_TZ),
            "note": "Manual half-day",
            "source_type": "manual",
        }
    ]
    
    rule_entries = [
        {
            "date": date(2025, 1, 6),
            "start_at": datetime(2025, 1, 6, 0, 0, tzinfo=ISRAEL_TZ),
            "end_at": datetime(2025, 1, 6, 23, 59, tzinfo=ISRAEL_TZ),
            "source_type": "rule",
            "source_rule_id": 1,
            "note": "Rule all-day",
        },
        {
            "date": date(2025, 1, 13),
            "start_at": datetime(2025, 1, 13, 0, 0, tzinfo=ISRAEL_TZ),
            "end_at": datetime(2025, 1, 13, 23, 59, tzinfo=ISRAEL_TZ),
            "source_type": "rule",
            "source_rule_id": 1,
            "note": "Rule all-day",
        }
    ]
    
    merged = merge_unavailability(manual_entries, rule_entries)
    
    # Should have 2 entries: manual on Jan 6, rule on Jan 13
    assert len(merged) == 2
    
    # Jan 6 should be manual (not rule)
    jan_6_entries = [e for e in merged if (e.get("date") == date(2025, 1, 6) or 
                                            (isinstance(e.get("start_at"), datetime) and e.get("start_at").date() == date(2025, 1, 6)))]
    assert len(jan_6_entries) == 1
    jan_6_entry = jan_6_entries[0]
    assert jan_6_entry["source_type"] == "manual"
    assert jan_6_entry["note"] == "Manual half-day"
    
    # Jan 13 should be rule
    jan_13_entries = [e for e in merged if e.get("date") == date(2025, 1, 13)]
    assert len(jan_13_entries) == 1
    jan_13_entry = jan_13_entries[0]
    assert jan_13_entry["source_type"] == "rule"


def test_check_event_conflicts():
    """Test event conflict detection."""
    event = {
        "event_id": 1,
        "event_date": date(2025, 1, 15),
        "load_in_time": time(17, 0),
        "show_time": time(20, 0),
    }
    
    # Employee unavailable 14:00-18:00 (conflicts with load_in)
    unavailability = [
        {
            "start_at": datetime(2025, 1, 15, 14, 0, tzinfo=ISRAEL_TZ),
            "end_at": datetime(2025, 1, 15, 18, 0, tzinfo=ISRAEL_TZ),
            "note": "Unavailable afternoon",
            "source_type": "manual",
        }
    ]
    
    conflict = check_event_conflicts(event, 1, unavailability)
    
    assert conflict is not None
    assert conflict["employee_id"] == 1
    assert conflict["event_id"] == 1
    assert conflict["note"] == "Unavailable afternoon"


def test_check_event_no_conflict():
    """Test that no conflict is detected when employee is available."""
    event = {
        "event_id": 1,
        "event_date": date(2025, 1, 15),
        "load_in_time": time(17, 0),
        "show_time": time(20, 0),
    }
    
    # Employee unavailable in morning (no conflict)
    unavailability = [
        {
            "start_at": datetime(2025, 1, 15, 8, 0, tzinfo=ISRAEL_TZ),
            "end_at": datetime(2025, 1, 15, 12, 0, tzinfo=ISRAEL_TZ),
            "note": "Unavailable morning",
            "source_type": "manual",
        }
    ]
    
    conflict = check_event_conflicts(event, 1, unavailability)
    
    assert conflict is None


def test_timezone_handling():
    """Test that all datetime conversions use Asia/Jerusalem timezone."""
    rule = {
        "rule_id": 8,
        "pattern": "weekly",
        "days_of_week": [0],  # Sunday
        "start_date": date(2025, 1, 1),
        "until_date": None,
        "all_day": False,
        "start_time": time(10, 0),
        "end_time": time(15, 0),
        "notes": "Timezone test",
    }
    
    occurrences = expand_rule_for_month(rule, 2025, 1, exceptions=[])
    
    # Check that all timestamps have correct timezone
    for occ in occurrences:
        assert occ["start_at"].tzinfo == ISRAEL_TZ
        assert occ["end_at"].tzinfo == ISRAEL_TZ
