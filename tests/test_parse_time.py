"""Tests for parse_time helper function."""

import pytest
from datetime import time, datetime

from app.time_utils import parse_time


def test_parse_time_with_time_object():
    """Test parse_time with datetime.time object returns it unchanged."""
    input_time = time(21, 0)
    result = parse_time(input_time)
    assert result == time(21, 0)
    assert isinstance(result, time)


def test_parse_time_with_string_hhmm():
    """Test parse_time with HH:MM string format."""
    result = parse_time("21:00")
    assert result == time(21, 0)
    assert isinstance(result, time)


def test_parse_time_with_string_hhmmss():
    """Test parse_time with HH:MM:SS string format."""
    result = parse_time("21:00:00")
    assert result == time(21, 0)
    assert isinstance(result, time)


def test_parse_time_with_string_hhmmss_nonzero_seconds():
    """Test parse_time with HH:MM:SS string format with non-zero seconds."""
    result = parse_time("21:30:45")
    assert result == time(21, 30, 45)
    assert isinstance(result, time)


def test_parse_time_with_none():
    """Test parse_time with None returns None."""
    result = parse_time(None)
    assert result is None


def test_parse_time_with_empty_string():
    """Test parse_time with empty string returns None."""
    result = parse_time("")
    assert result is None
    
    result = parse_time("   ")
    assert result is None


def test_parse_time_with_datetime_object():
    """Test parse_time with datetime object extracts time part."""
    dt = datetime(2024, 12, 24, 21, 30, 45)
    result = parse_time(dt)
    assert result == time(21, 30, 45)
    assert isinstance(result, time)


def test_parse_time_with_invalid_string():
    """Test parse_time with invalid string format raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        parse_time("invalid")
    assert "Invalid time format" in str(exc_info.value)
    
    with pytest.raises(ValueError) as exc_info:
        parse_time("25:00")  # Invalid hour
    assert "Invalid time format" in str(exc_info.value)


def test_parse_time_with_invalid_type():
    """Test parse_time with invalid type raises TypeError."""
    with pytest.raises(TypeError) as exc_info:
        parse_time(12345)
    assert "Cannot parse time from type" in str(exc_info.value)
    
    with pytest.raises(TypeError) as exc_info:
        parse_time([21, 0])
    assert "Cannot parse time from type" in str(exc_info.value)


def test_parse_time_edge_cases():
    """Test parse_time with edge case times."""
    # Midnight
    assert parse_time("00:00") == time(0, 0)
    assert parse_time("00:00:00") == time(0, 0)
    
    # End of day
    assert parse_time("23:59") == time(23, 59)
    assert parse_time("23:59:59") == time(23, 59, 59)
    
    # Single digit hours are accepted (strptime is lenient)
    assert parse_time("9:00") == time(9, 0)
    assert parse_time("9:30:00") == time(9, 30)
