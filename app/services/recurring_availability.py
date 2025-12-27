"""
Recurring Availability Service

Handles expansion of recurring unavailability rules into specific date/time occurrences.
Implements precedence logic: manual overrides > rule occurrences, exceptions cancel rule occurrences.
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def expand_rule_for_month(
    rule: dict,
    year: int,
    month: int,
    exceptions: List[date] = None,
) -> List[Dict]:
    """
    Expand a recurring rule into specific occurrences for a given month.
    
    Args:
        rule: Rule dict with pattern, days_of_week, day_of_month, start_time, end_time, etc.
        year: Year to expand
        month: Month to expand (1-12)
        exceptions: List of dates to exclude from expansion
    
    Returns:
        List of occurrence dicts with date, start_at, end_at, source info
    """
    from calendar import monthrange
    
    exceptions = exceptions or []
    occurrences = []
    
    pattern = rule.get("pattern")
    start_date = rule.get("start_date")
    until_date = rule.get("until_date")
    all_day = rule.get("all_day", False)
    start_time = rule.get("start_time")
    end_time = rule.get("end_time")
    
    # Convert dates to date objects if needed
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    elif isinstance(start_date, datetime):
        start_date = start_date.date()
    
    if until_date:
        if isinstance(until_date, str):
            until_date = date.fromisoformat(until_date)
        elif isinstance(until_date, datetime):
            until_date = until_date.date()
    
    # Calculate month boundaries
    month_start = date(year, month, 1)
    _, last_day = monthrange(year, month)
    month_end = date(year, month, last_day)
    
    # Rule must be active during this month
    if start_date > month_end or (until_date and until_date < month_start):
        return []
    
    if pattern == "weekly":
        occurrences = _expand_weekly(
            rule, month_start, month_end, start_date, until_date, exceptions
        )
    elif pattern == "biweekly":
        occurrences = _expand_biweekly(
            rule, month_start, month_end, start_date, until_date, exceptions
        )
    elif pattern == "monthly":
        occurrences = _expand_monthly(
            rule, month_start, month_end, start_date, until_date, exceptions
        )
    else:
        logger.warning(f"Unknown pattern: {pattern}")
        return []
    
    # Convert occurrences to timestamptz ranges
    result = []
    for occ_date in occurrences:
        if all_day:
            # All day = start of day to end of day in Israel time
            start_at = datetime.combine(occ_date, time(0, 0), tzinfo=ISRAEL_TZ)
            # Use the last moment of the day to include all seconds
            end_at = datetime.combine(occ_date, time(23, 59, 59, 999999), tzinfo=ISRAEL_TZ)
        else:
            # Use specific start/end times
            if not start_time or not end_time:
                logger.warning(f"Rule {rule.get('rule_id')} has all_day=False but missing times")
                continue
            
            # Convert time objects if needed
            if isinstance(start_time, str):
                start_time = time.fromisoformat(start_time)
            if isinstance(end_time, str):
                end_time = time.fromisoformat(end_time)
            
            start_at = datetime.combine(occ_date, start_time, tzinfo=ISRAEL_TZ)
            end_at = datetime.combine(occ_date, end_time, tzinfo=ISRAEL_TZ)
        
        result.append({
            "date": occ_date,
            "start_at": start_at,
            "end_at": end_at,
            "source_type": "rule",
            "source_rule_id": rule.get("rule_id"),
            "note": rule.get("notes"),
        })
    
    return result


def _expand_weekly(
    rule: dict,
    month_start: date,
    month_end: date,
    start_date: date,
    until_date: Optional[date],
    exceptions: List[date],
) -> List[date]:
    """Expand weekly pattern into specific dates."""
    days_of_week = rule.get("days_of_week", [])
    if not days_of_week:
        return []
    
    occurrences = []
    current = max(month_start, start_date)
    
    while current <= month_end:
        if until_date and current > until_date:
            break
        
        # Check if this day of week is in the pattern
        # weekday() returns 0=Monday, 6=Sunday, but our pattern uses 0=Sunday
        weekday = (current.weekday() + 1) % 7  # Convert to 0=Sunday
        
        if weekday in days_of_week and current not in exceptions:
            occurrences.append(current)
        
        current += timedelta(days=1)
    
    return occurrences


def _expand_biweekly(
    rule: dict,
    month_start: date,
    month_end: date,
    start_date: date,
    until_date: Optional[date],
    exceptions: List[date],
) -> List[date]:
    """
    Expand biweekly pattern into specific dates.
    
    Uses anchor_date to determine which weeks are "on" weeks.
    Week numbers are calculated from anchor_date, where week 0, 2, 4, ... are active.
    """
    days_of_week = rule.get("days_of_week", [])
    if not days_of_week:
        return []
    
    anchor_date = rule.get("anchor_date")
    if not anchor_date:
        anchor_date = start_date
    
    # Convert anchor_date if needed
    if isinstance(anchor_date, str):
        anchor_date = date.fromisoformat(anchor_date)
    elif isinstance(anchor_date, datetime):
        anchor_date = anchor_date.date()
    
    occurrences = []
    current = max(month_start, start_date)
    
    while current <= month_end:
        if until_date and current > until_date:
            break
        
        # Calculate weeks since anchor
        days_since_anchor = (current - anchor_date).days
        week_number = days_since_anchor // 7
        
        # Only include even weeks (0, 2, 4, ...)
        if week_number % 2 == 0:
            weekday = (current.weekday() + 1) % 7  # Convert to 0=Sunday
            
            if weekday in days_of_week and current not in exceptions:
                occurrences.append(current)
        
        current += timedelta(days=1)
    
    return occurrences


def _expand_monthly(
    rule: dict,
    month_start: date,
    month_end: date,
    start_date: date,
    until_date: Optional[date],
    exceptions: List[date],
) -> List[date]:
    """Expand monthly pattern into specific dates."""
    day_of_month = rule.get("day_of_month")
    if not day_of_month:
        return []
    
    occurrences = []
    
    # Check each month that overlaps with the requested range
    current_year = month_start.year
    current_month = month_start.month
    
    while date(current_year, current_month, 1) <= month_end:
        # Check if day exists in this month
        from calendar import monthrange
        _, days_in_month = monthrange(current_year, current_month)
        
        if day_of_month <= days_in_month:
            occurrence = date(current_year, current_month, day_of_month)
            
            # Check if within valid range
            if occurrence >= start_date:
                if until_date and occurrence > until_date:
                    break
                
                if occurrence not in exceptions and month_start <= occurrence <= month_end:
                    occurrences.append(occurrence)
        
        # Move to next month
        if current_month == 12:
            current_month = 1
            current_year += 1
        else:
            current_month += 1
    
    return occurrences


def merge_unavailability(
    manual_entries: List[dict],
    rule_entries: List[dict],
) -> List[dict]:
    """
    Merge manual and rule-based unavailability entries with proper precedence.
    
    Precedence: manual overrides rule on same date/time range.
    
    Args:
        manual_entries: List of manual unavailability blocks
        rule_entries: List of rule-generated occurrences
    
    Returns:
        Merged list with proper precedence applied
    """
    # Index manual entries by date for quick lookup
    manual_by_date = {}
    for entry in manual_entries:
        start_at = entry["start_at"]
        if isinstance(start_at, str):
            start_at = datetime.fromisoformat(start_at)
        
        entry_date = start_at.date()
        if entry_date not in manual_by_date:
            manual_by_date[entry_date] = []
        manual_by_date[entry_date].append(entry)
    
    # Filter rule entries that don't conflict with manual
    result = list(manual_entries)  # Start with all manual entries
    
    for rule_entry in rule_entries:
        entry_date = rule_entry["date"]
        
        # If there's a manual entry on this date, skip the rule entry
        if entry_date not in manual_by_date:
            result.append(rule_entry)
    
    return result


def check_event_conflicts(
    event: dict,
    employee_id: int,
    unavailability: List[dict],
) -> Optional[Dict]:
    """
    Check if an employee has unavailability that conflicts with an event.
    
    Args:
        event: Event dict with date, load_in_time, show_time, end_time
        employee_id: Employee to check
        unavailability: List of unavailability entries (manual + rules)
    
    Returns:
        Conflict dict if found, None otherwise
    """
    # Calculate event window
    event_date = event.get("event_date")
    if isinstance(event_date, str):
        event_date = date.fromisoformat(event_date)
    elif isinstance(event_date, datetime):
        event_date = event_date.date()
    
    # Determine event start time (load_in or show_time)
    load_in = event.get("load_in_time")
    show_time = event.get("show_time")
    
    if load_in:
        if isinstance(load_in, str):
            load_in = time.fromisoformat(load_in)
        event_start = datetime.combine(event_date, load_in, tzinfo=ISRAEL_TZ)
    elif show_time:
        if isinstance(show_time, str):
            show_time = time.fromisoformat(show_time)
        event_start = datetime.combine(event_date, show_time, tzinfo=ISRAEL_TZ)
    else:
        # Fallback: assume start of day
        event_start = datetime.combine(event_date, time(0, 0), tzinfo=ISRAEL_TZ)
    
    # Determine event end time (fallback to show + 4 hours)
    end_time = event.get("end_time")
    if end_time:
        if isinstance(end_time, str):
            end_time = time.fromisoformat(end_time)
        event_end = datetime.combine(event_date, end_time, tzinfo=ISRAEL_TZ)
    elif show_time:
        event_end = event_start + timedelta(hours=4)  # Reasonable fallback
    else:
        event_end = event_start + timedelta(hours=8)  # Full work day fallback
    
    # Check for conflicts
    for unavail in unavailability:
        unavail_start = unavail.get("start_at")
        unavail_end = unavail.get("end_at")
        
        # Convert to datetime if needed
        if isinstance(unavail_start, str):
            unavail_start = datetime.fromisoformat(unavail_start)
        if isinstance(unavail_end, str):
            unavail_end = datetime.fromisoformat(unavail_end)
        
        # Make timezone-aware if needed
        if unavail_start.tzinfo is None:
            unavail_start = unavail_start.replace(tzinfo=ISRAEL_TZ)
        if unavail_end.tzinfo is None:
            unavail_end = unavail_end.replace(tzinfo=ISRAEL_TZ)
        
        # Check for overlap
        if unavail_start < event_end and unavail_end > event_start:
            return {
                "employee_id": employee_id,
                "event_id": event.get("event_id"),
                "unavail_start": unavail_start,
                "unavail_end": unavail_end,
                "event_start": event_start,
                "event_end": event_end,
                "note": unavail.get("note"),
                "source_type": unavail.get("source_type", "manual"),
                "source_rule_id": unavail.get("source_rule_id"),
            }
    
    return None
