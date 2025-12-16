"""
Centralized timezone utilities for HOH Bot.

This module provides the single source of truth for all time/timezone operations.
All times are stored in the database as UTC (TIMESTAMPTZ) and converted to/from
Asia/Jerusalem timezone for display and user input.

Key principles:
- Database stores everything in UTC
- UI displays and accepts times in Asia/Jerusalem local time
- All datetime objects should be timezone-aware
- No manual hour offsets - let zoneinfo handle DST automatically
"""

import logging
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from typing import Optional

logger = logging.getLogger(__name__)

# Israel timezone - handles DST automatically
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def get_il_tz() -> ZoneInfo:
    """
    Get the Israel timezone object.
    
    Returns:
        ZoneInfo object for Asia/Jerusalem
    """
    return ISRAEL_TZ


def parse_local_time_to_utc(event_date: date, hhmm: str) -> datetime:
    """
    Parse a local Israel time string and combine with date to create UTC datetime.
    
    This function takes a date and a time string in HH:MM format (local Israel time),
    combines them into a timezone-aware datetime in Asia/Jerusalem, then converts
    to UTC.
    
    Args:
        event_date: The date for the event
        hhmm: Time string in "HH:MM" format (local Israel time)
        
    Returns:
        Timezone-aware datetime in UTC
        
    Example:
        >>> parse_local_time_to_utc(date(2024, 7, 15), "21:00")
        # Returns datetime representing 21:00 Israel time (18:00 UTC in summer)
        >>> parse_local_time_to_utc(date(2024, 1, 15), "21:00")
        # Returns datetime representing 21:00 Israel time (19:00 UTC in winter)
    """
    time_part = datetime.strptime(hhmm, "%H:%M").time()
    
    # Create a naive datetime first
    local_naive = datetime.combine(event_date, time_part)
    
    # Localize to Israel timezone (handles DST correctly)
    local_aware = local_naive.replace(tzinfo=ISRAEL_TZ)
    
    # Convert to UTC
    utc_aware = local_aware.astimezone(timezone.utc)
    
    logger.debug(
        "Converted local time %s %s (Israel) -> %s (UTC)",
        event_date,
        hhmm,
        utc_aware.isoformat()
    )
    
    return utc_aware


def utc_to_local_datetime(dt_utc: datetime) -> datetime:
    """
    Convert a UTC datetime to Israel local timezone.
    
    Args:
        dt_utc: Timezone-aware datetime in UTC (or naive assumed to be UTC)
        
    Returns:
        Timezone-aware datetime in Asia/Jerusalem
    """
    if dt_utc is None:
        return None
        
    # Ensure it's aware - if naive, assume UTC
    if dt_utc.tzinfo is None:
        logger.warning(
            "Received naive datetime %s, assuming UTC. "
            "This should be fixed at the source.",
            dt_utc
        )
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    
    # Convert to Israel time
    return dt_utc.astimezone(ISRAEL_TZ)


def utc_to_local_time_str(dt_utc: datetime) -> str:
    """
    Convert a UTC datetime to local Israel time string in HH:MM format.
    
    Args:
        dt_utc: Timezone-aware datetime in UTC (or naive assumed to be UTC)
        
    Returns:
        Time string in "HH:MM" format (Israel local time)
    """
    if dt_utc is None:
        return ""
    
    local_dt = utc_to_local_datetime(dt_utc)
    return local_dt.strftime("%H:%M")


def utc_to_local_date_str(dt_utc: datetime, format: str = "%d.%m.%Y") -> str:
    """
    Convert a UTC datetime to local Israel date string.
    
    Args:
        dt_utc: Timezone-aware datetime in UTC (or naive assumed to be UTC)
        format: Date format string (default: DD.MM.YYYY)
        
    Returns:
        Date string in specified format (Israel local date)
    """
    if dt_utc is None:
        return ""
    
    local_dt = utc_to_local_datetime(dt_utc)
    return local_dt.strftime(format)


def ensure_aware(dt: datetime, assume_utc: bool = True) -> datetime:
    """
    Ensure a datetime is timezone-aware.
    
    This is a safety function. Ideally, all datetimes should already be aware.
    If a naive datetime is received, this logs a warning and makes it aware.
    
    Args:
        dt: Datetime that may be naive or aware
        assume_utc: If True and dt is naive, assume it's UTC. 
                   If False, assume it's Israel time.
        
    Returns:
        Timezone-aware datetime
    """
    if dt is None:
        return None
        
    if dt.tzinfo is not None:
        # Already aware, return as-is
        return dt
    
    # Naive datetime - log warning and fix
    logger.warning(
        "Received naive datetime %s. Assuming %s timezone. "
        "This should be fixed at the source to avoid ambiguity.",
        dt,
        "UTC" if assume_utc else "Israel"
    )
    
    if assume_utc:
        return dt.replace(tzinfo=timezone.utc)
    else:
        return dt.replace(tzinfo=ISRAEL_TZ)


def now_utc() -> datetime:
    """
    Get current time as timezone-aware UTC datetime.
    
    Returns:
        Current datetime in UTC
    """
    return datetime.now(timezone.utc)


def now_israel() -> datetime:
    """
    Get current time as timezone-aware Israel datetime.
    
    Returns:
        Current datetime in Asia/Jerusalem timezone
    """
    return datetime.now(ISRAEL_TZ)


def format_datetime_for_display(dt: datetime, include_date: bool = True) -> str:
    """
    Format a datetime for display in Israel timezone.
    
    Args:
        dt: Timezone-aware datetime (typically from DB in UTC)
        include_date: If True, include date in format "DD/MM/YYYY HH:MM"
                     If False, only time "HH:MM"
    
    Returns:
        Formatted string in Israel local time
    """
    if dt is None:
        return ""
    
    local_dt = utc_to_local_datetime(dt)
    
    if include_date:
        return local_dt.strftime("%d/%m/%Y %H:%M")
    else:
        return local_dt.strftime("%H:%M")
