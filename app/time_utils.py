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
    to UTC. Automatically handles DST transitions.
    
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
    
    # Combine date and time with timezone in one step
    # This is safe with zoneinfo (unlike pytz) and handles DST correctly
    local_aware = datetime.combine(event_date, time_part, tzinfo=ISRAEL_TZ)
    
    # Convert to UTC
    utc_aware = local_aware.astimezone(timezone.utc)
    
    logger.debug(
        "Converted local time %s %s (Israel) -> %s (UTC)",
        event_date,
        hhmm,
        utc_aware.isoformat()
    )
    
    return utc_aware


def utc_to_local_datetime(dt: datetime) -> datetime:
    """
    Convert a datetime (expected to be UTC) to Israel local timezone.
    
    Args:
        dt: Timezone-aware datetime, preferably in UTC. 
            If naive, it will be assumed to be UTC with a warning.
        
    Returns:
        Timezone-aware datetime in Asia/Jerusalem, or None if input is None
    """
    if dt is None:
        return None
        
    # Ensure it's aware - if naive, assume UTC
    if dt.tzinfo is None:
        logger.warning(
            "Received naive datetime %s, assuming UTC. "
            "This should be fixed at the source.",
            dt
        )
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Convert to Israel time
    return dt.astimezone(ISRAEL_TZ)


def utc_to_local_time_str(dt: datetime) -> str:
    """
    Convert a datetime (expected to be UTC) to local Israel time string in HH:MM format.
    
    Args:
        dt: Timezone-aware datetime, preferably in UTC.
            If naive, it will be assumed to be UTC with a warning.
        
    Returns:
        Time string in "HH:MM" format (Israel local time), or empty string if input is None
    """
    if dt is None:
        return ""
    
    local_dt = utc_to_local_datetime(dt)
    return local_dt.strftime("%H:%M")


def utc_to_local_date_str(dt: datetime, format: str = "%d.%m.%Y") -> str:
    """
    Convert a datetime (expected to be UTC) to local Israel date string.
    
    Args:
        dt: Timezone-aware datetime, preferably in UTC.
            If naive, it will be assumed to be UTC with a warning.
        format: Date format string (default: DD.MM.YYYY)
        
    Returns:
        Date string in specified format (Israel local date), or empty string if input is None
    """
    if dt is None:
        return ""
    
    local_dt = utc_to_local_datetime(dt)
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


def parse_datetime_local_input(datetime_local_str: str) -> datetime:
    """
    Parse a datetime-local input from HTML form and convert to timezone-aware datetime.
    
    HTML datetime-local inputs send strings in format "YYYY-MM-DDTHH:MM" which
    represent the local time in the user's timezone. We treat these as Israel
    local times and convert to UTC-aware datetimes.
    
    Args:
        datetime_local_str: String in format "YYYY-MM-DDTHH:MM" (e.g., "2024-07-15T21:00")
        
    Returns:
        Timezone-aware datetime in Israel timezone, ready to be stored as UTC in DB
        
    Example:
        >>> parse_datetime_local_input("2024-07-15T21:00")
        # Returns 2024-07-15 21:00:00+03:00 (Israel time in summer)
    """
    # Parse the ISO format datetime (this creates a naive datetime)
    dt_naive = datetime.fromisoformat(datetime_local_str)
    
    # Treat as Israel local time by attaching the timezone
    # This is safe with zoneinfo and handles DST correctly
    dt_aware = dt_naive.replace(tzinfo=ISRAEL_TZ)
    
    return dt_aware


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


def compute_send_at(
    base_date: date,
    fixed_time: str,
    days_before: int,
    now: datetime,
    apply_weekend_rule: bool
) -> datetime:
    """
    Calculate the send_at timestamp for scheduled messages with weekend rule support.
    
    This function is used for scheduling messages like INIT, TECH_REMINDER, and SHIFT_REMINDER.
    The weekend rule applies ONLY for INIT messages - TECH_REMINDER and SHIFT_REMINDER can be 
    sent on Friday/Saturday.
    
    Algorithm:
    1) Calculate candidate = (base_date at fixed_time in Asia/Jerusalem) - days_before days
    2) If candidate < now: candidate = (tomorrow at fixed_time)
    3) If apply_weekend_rule is True:
       - If candidate is Friday -> add 2 days (Sunday)
       - If candidate is Saturday -> add 1 day (Sunday)
    
    Args:
        base_date: The base event date (e.g., event_date)
        fixed_time: Time string in "HH:MM" format for the scheduled message (e.g., "09:00")
        days_before: Number of days before base_date to schedule (e.g., 3 for "3 days before event")
        now: Current datetime (timezone-aware, for comparison)
        apply_weekend_rule: If True, move Friday/Saturday to Sunday (use for INIT only)
    
    Returns:
        Timezone-aware datetime in UTC representing when the message should be sent
        
    Examples:
        # INIT message 3 days before event on Thursday at 09:00
        >>> compute_send_at(date(2024, 7, 18), "09:00", 3, now_utc(), True)
        # Returns Monday 2024-07-15 09:00 Israel time (as UTC)
        
        # INIT message would be Friday, moved to Sunday
        >>> compute_send_at(date(2024, 7, 20), "09:00", 1, now_utc(), True)
        # Returns Sunday 2024-07-21 09:00 Israel time (as UTC)
        
        # TECH_REMINDER on Friday - no weekend rule
        >>> compute_send_at(date(2024, 7, 20), "09:00", 1, now_utc(), False)
        # Returns Friday 2024-07-19 09:00 Israel time (as UTC)
    """
    from datetime import timedelta
    
    # Ensure now is timezone-aware
    if now.tzinfo is None:
        logger.warning("compute_send_at received naive datetime for 'now', assuming UTC")
        now = now.replace(tzinfo=timezone.utc)
    
    # Step 1: Calculate initial candidate = base_date - days_before at fixed_time
    candidate_date = base_date - timedelta(days=days_before)
    
    # Parse the time and combine with candidate_date in Israel timezone
    candidate = parse_local_time_to_utc(candidate_date, fixed_time)
    
    # Step 2: If candidate is in the past, move to tomorrow at fixed_time
    if candidate < now:
        # Get tomorrow's date in Israel timezone
        now_israel = utc_to_local_datetime(now)
        tomorrow_israel = now_israel.date() + timedelta(days=1)
        candidate = parse_local_time_to_utc(tomorrow_israel, fixed_time)
    
    # Step 3: Apply weekend rule if requested (INIT messages only)
    if apply_weekend_rule:
        # Convert to Israel time to check the weekday
        candidate_israel = utc_to_local_datetime(candidate)
        weekday = candidate_israel.weekday()  # Monday=0, Sunday=6
        
        if weekday == 4:  # Friday
            # Move to Sunday (add 2 days)
            new_date = candidate_israel.date() + timedelta(days=2)
            candidate = parse_local_time_to_utc(new_date, fixed_time)
            logger.info(
                "Weekend rule: Moving from Friday to Sunday: %s -> %s",
                candidate_israel.date(),
                new_date
            )
        elif weekday == 5:  # Saturday
            # Move to Sunday (add 1 day)
            new_date = candidate_israel.date() + timedelta(days=1)
            candidate = parse_local_time_to_utc(new_date, fixed_time)
            logger.info(
                "Weekend rule: Moving from Saturday to Sunday: %s -> %s",
                candidate_israel.date(),
                new_date
            )
    
    return candidate
