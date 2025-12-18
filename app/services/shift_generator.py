"""
Shift Generator Service - Core logic for automatic shift assignment.

This service implements the shift generation algorithm with hard constraints
and heuristic-based employee ranking.
"""

import random
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Default settings (can be made configurable later)
DEFAULT_SHIFT_HOURS = 8
MAX_SHIFT_HOURS = 12
MIN_REST_HOURS = 10
NIGHT_START_HOUR = 22  # 22:00
NIGHT_END_HOUR = 6      # 06:00
MORNING_START_HOUR = 6  # 06:00
MORNING_END_HOUR = 12   # 12:00
EVENT_BUFFER_HOURS = 5  # Hours after show_time

# Weekend definition: Friday 15:00 to Saturday 23:59
WEEKEND_START_DAY = 4  # Friday (0=Monday)
WEEKEND_START_HOUR = 15
WEEKEND_END_DAY = 5  # Saturday
WEEKEND_END_HOUR = 23
WEEKEND_END_MINUTE = 59


def create_slots_for_event(event: dict) -> list[dict]:
    """
    Create shift slots for an event based on its duration.
    
    If event duration > 12 hours, split into multiple slots.
    Returns list of slot dicts with start_at and end_at.
    """
    load_in = event.get("load_in_time")
    show_time = event.get("show_time")
    event_date = event.get("event_date")
    
    if not load_in or not show_time or not event_date:
        return []
    
    # Convert to datetime objects
    from datetime import datetime as dt, date, time
    
    if isinstance(event_date, str):
        event_date = date.fromisoformat(event_date)
    elif isinstance(event_date, dt):
        event_date = event_date.date()
    
    # Handle load_in_time and show_time which might be time or datetime
    if isinstance(load_in, str):
        load_in = time.fromisoformat(load_in.split('+')[0])
    elif isinstance(load_in, dt):
        load_in = load_in.time()
    
    if isinstance(show_time, str):
        show_time = time.fromisoformat(show_time.split('+')[0])
    elif isinstance(show_time, dt):
        show_time = show_time.time()
    
    # Create timezone-aware datetimes
    start_dt = dt.combine(event_date, load_in).replace(tzinfo=ISRAEL_TZ)
    end_dt = dt.combine(event_date, show_time).replace(tzinfo=ISRAEL_TZ) + timedelta(hours=EVENT_BUFFER_HOURS)
    
    # Handle case where show_time is on the next day
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    
    total_hours = (end_dt - start_dt).total_seconds() / 3600
    
    slots = []
    
    if total_hours <= MAX_SHIFT_HOURS:
        # Single slot
        slots.append({
            "start_at": start_dt,
            "end_at": end_dt,
            "event_id": event["event_id"],
        })
    else:
        # Split into multiple slots
        current_start = start_dt
        while current_start < end_dt:
            # Prefer 8-hour slots, but last slot can be shorter
            remaining_hours = (end_dt - current_start).total_seconds() / 3600
            
            if remaining_hours <= MAX_SHIFT_HOURS:
                # Last slot
                slot_end = end_dt
            else:
                # Standard slot (8 hours preferred)
                slot_end = current_start + timedelta(hours=DEFAULT_SHIFT_HOURS)
            
            slots.append({
                "start_at": current_start,
                "end_at": slot_end,
                "event_id": event["event_id"],
            })
            
            current_start = slot_end
    
    return slots


def is_weekend_shift(start_at: datetime) -> bool:
    """Check if a shift starts during weekend (Friday 15:00 - Saturday 23:59)."""
    weekday = start_at.weekday()  # 0=Monday, 4=Friday, 5=Saturday
    hour = start_at.hour
    minute = start_at.minute
    
    if weekday == WEEKEND_START_DAY:  # Friday
        return hour >= WEEKEND_START_HOUR
    elif weekday == WEEKEND_END_DAY:  # Saturday
        return hour < WEEKEND_END_HOUR or (hour == WEEKEND_END_HOUR and minute <= WEEKEND_END_MINUTE)
    
    return False


def is_night_shift(start_at: datetime, end_at: datetime) -> bool:
    """Check if shift overlaps with night hours (22:00 - 06:00)."""
    # A shift touches night if any part of it is between 22:00 and 06:00
    hour_start = start_at.hour
    hour_end = end_at.hour
    
    # Check if shift starts or ends in night hours, or spans across midnight
    is_night = False
    
    # Shift starts in night hours
    if hour_start >= NIGHT_START_HOUR or hour_start < NIGHT_END_HOUR:
        is_night = True
    
    # Shift ends in night hours  
    if hour_end >= NIGHT_START_HOUR or hour_end < NIGHT_END_HOUR:
        is_night = True
    
    # Shift spans across the night period
    if hour_start < NIGHT_START_HOUR and hour_end >= NIGHT_START_HOUR:
        is_night = True
    
    return is_night


def is_morning_shift(start_at: datetime) -> bool:
    """Check if shift starts in morning hours (06:00 - 12:00)."""
    return MORNING_START_HOUR <= start_at.hour < MORNING_END_HOUR


def violates_night_to_morning_rule(
    employee_shifts: list[dict],
    slot_start: datetime,
) -> bool:
    """
    Check if assigning this slot violates the night->morning rule.
    
    Rule: If employee worked a night shift, they cannot work a morning shift
    the next day.
    """
    slot_date = slot_start.date()
    
    # Check if this slot is a morning shift
    if not is_morning_shift(slot_start):
        return False  # Rule only applies to morning shifts
    
    # Check if employee worked a night shift the previous day
    previous_date = slot_date - timedelta(days=1)
    
    for shift in employee_shifts:
        shift_start = shift.get("start_at") or shift.get("call_time")
        shift_end = shift.get("end_at")
        
        if not shift_start:
            continue
        
        # Ensure timezone-aware
        if shift_start.tzinfo is None:
            shift_start = shift_start.replace(tzinfo=ISRAEL_TZ)
        if shift_end and shift_end.tzinfo is None:
            shift_end = shift_end.replace(tzinfo=ISRAEL_TZ)
        
        shift_date = shift_start.date()
        
        # Check if this shift was on the previous day and touched night hours
        if shift_date == previous_date:
            if shift_end:
                if is_night_shift(shift_start, shift_end):
                    return True  # Violation!
            else:
                # No end time, check if start was in night hours
                if shift_start.hour >= NIGHT_START_HOUR or shift_start.hour < NIGHT_END_HOUR:
                    return True
    
    return False


def has_sufficient_rest(
    employee_shifts: list[dict],
    slot_start: datetime,
) -> bool:
    """
    Check if employee has at least MIN_REST_HOURS between shifts.
    
    Returns True if sufficient rest, False otherwise.
    """
    for shift in employee_shifts:
        shift_end = shift.get("end_at")
        shift_start = shift.get("start_at") or shift.get("call_time")
        
        if not shift_start:
            continue
        
        # Ensure timezone-aware
        if shift_start.tzinfo is None:
            shift_start = shift_start.replace(tzinfo=ISRAEL_TZ)
        if shift_end and shift_end.tzinfo is None:
            shift_end = shift_end.replace(tzinfo=ISRAEL_TZ)
        
        # If we don't have end time, assume shift is 8 hours
        if not shift_end:
            shift_end = shift_start + timedelta(hours=DEFAULT_SHIFT_HOURS)
        
        # Check rest time: slot_start should be at least MIN_REST_HOURS after shift_end
        rest_hours = (slot_start - shift_end).total_seconds() / 3600
        
        if rest_hours < MIN_REST_HOURS and rest_hours > -MAX_SHIFT_HOURS:
            # Overlapping or insufficient rest
            return False
    
    return True


def has_availability_conflict(
    unavailability_blocks: list[dict],
    slot_start: datetime,
    slot_end: datetime,
) -> bool:
    """Check if slot overlaps with any unavailability block."""
    for block in unavailability_blocks:
        block_start = block["start_at"]
        block_end = block["end_at"]
        
        # Ensure timezone-aware
        if block_start.tzinfo is None:
            block_start = block_start.replace(tzinfo=ISRAEL_TZ)
        if block_end.tzinfo is None:
            block_end = block_end.replace(tzinfo=ISRAEL_TZ)
        
        # Check overlap: slot overlaps if it starts before block ends and ends after block starts
        if slot_start < block_end and slot_end > block_start:
            return True
    
    return False


def worked_yesterday(employee_shifts: list[dict], slot_date: datetime) -> bool:
    """Check if employee worked on the previous day."""
    yesterday = slot_date.date() - timedelta(days=1)
    
    for shift in employee_shifts:
        shift_start = shift.get("start_at") or shift.get("call_time")
        
        if not shift_start:
            continue
        
        # Ensure timezone-aware
        if shift_start.tzinfo is None:
            shift_start = shift_start.replace(tzinfo=ISRAEL_TZ)
        
        # Check if shift was on yesterday
        if shift_start.date() == yesterday:
            return True
    
    return False


def count_weekend_shifts(employee_shifts: list[dict]) -> int:
    """Count weekend shifts for an employee."""
    count = 0
    for shift in employee_shifts:
        shift_start = shift.get("start_at") or shift.get("call_time")
        
        if not shift_start:
            continue
        
        # Ensure timezone-aware
        if shift_start.tzinfo is None:
            shift_start = shift_start.replace(tzinfo=ISRAEL_TZ)
        
        if is_weekend_shift(shift_start):
            count += 1
    
    return count


def generate_shifts_for_events(
    events: list[dict],
    employees: list[dict],
    existing_shifts: list[dict],
    unavailability: list[dict],
    org_id: int,
    year: int,
    month: int,
) -> dict:
    """
    Generate shift assignments for all events in a month.
    
    Returns a dict with:
    - slots: list of slot assignments with suggested_employee_id
    - explainability: dict of rejection reasons per slot
    - employee_stats: dict of stats per employee
    """
    # Set random seed for stable results
    random.seed(f"{org_id}-{year}-{month}")
    
    # Build employee shift map
    employee_shift_map = {}
    for emp in employees:
        emp_id = emp["employee_id"]
        employee_shift_map[emp_id] = [
            s for s in existing_shifts if s["employee_id"] == emp_id
        ]
    
    # Build unavailability map
    unavailability_map = {}
    for emp in employees:
        emp_id = emp["employee_id"]
        unavailability_map[emp_id] = [
            u for u in unavailability if u["employee_id"] == emp_id
        ]
    
    # Generate slots for all events
    all_slots = []
    for event in events:
        slots = create_slots_for_event(event)
        all_slots.extend(slots)
    
    # Sort slots by start time
    all_slots.sort(key=lambda s: s["start_at"])
    
    # Assign employees to slots
    result_slots = []
    explainability = {}
    
    for slot_idx, slot in enumerate(all_slots):
        slot_id = f"slot_{slot_idx}"
        slot_start = slot["start_at"]
        slot_end = slot["end_at"]
        slot_duration = (slot_end - slot_start).total_seconds() / 3600
        
        # Check if slot duration exceeds max
        if slot_duration > MAX_SHIFT_HOURS:
            result_slots.append({
                **slot,
                "suggested_employee_id": None,
                "unfilled_reason": f"Slot duration ({slot_duration:.1f}h) exceeds max ({MAX_SHIFT_HOURS}h)",
            })
            explainability[slot_id] = {"error": "Slot too long"}
            continue
        
        # Evaluate all employees
        candidates = []
        rejections = {}
        
        for emp in employees:
            if not emp.get("is_active", True):
                rejections[emp["employee_id"]] = ["Employee not active"]
                continue
            
            emp_id = emp["employee_id"]
            emp_shifts = employee_shift_map[emp_id]
            emp_unavailability = unavailability_map[emp_id]
            
            reasons = []
            
            # Hard constraint checks
            if has_availability_conflict(emp_unavailability, slot_start, slot_end):
                reasons.append("Unavailable during this time")
            
            if not has_sufficient_rest(emp_shifts, slot_start):
                reasons.append(f"Less than {MIN_REST_HOURS}h rest from previous shift")
            
            if violates_night_to_morning_rule(emp_shifts, slot_start):
                reasons.append("Night→morning rule violation")
            
            # Check for overlapping shifts
            has_overlap = False
            for shift in emp_shifts:
                shift_start = shift.get("start_at") or shift.get("call_time")
                shift_end = shift.get("end_at")
                
                if not shift_start:
                    continue
                
                if shift_start.tzinfo is None:
                    shift_start = shift_start.replace(tzinfo=ISRAEL_TZ)
                if shift_end and shift_end.tzinfo is None:
                    shift_end = shift_end.replace(tzinfo=ISRAEL_TZ)
                
                if not shift_end:
                    shift_end = shift_start + timedelta(hours=DEFAULT_SHIFT_HOURS)
                
                # Check overlap
                if slot_start < shift_end and slot_end > shift_start:
                    has_overlap = True
                    break
            
            if has_overlap:
                reasons.append("Already assigned to another shift at this time")
            
            if reasons:
                rejections[emp_id] = reasons
                continue
            
            # Passed all hard constraints - calculate ranking score
            score = 0
            
            # Prefer employee who didn't work yesterday
            if not worked_yesterday(emp_shifts, slot_start):
                score += 100
            
            # Weekend fairness - prefer employees with fewer weekend shifts
            if is_weekend_shift(slot_start):
                weekend_count = count_weekend_shifts(emp_shifts)
                score -= weekend_count * 10
            
            # Total shift fairness - prefer employees with fewer total shifts
            total_shifts = len(emp_shifts)
            score -= total_shifts * 5
            
            # Add small random component for tie-breaking
            score += random.random()
            
            candidates.append({
                "employee_id": emp_id,
                "score": score,
                "employee": emp,
            })
        
        # Select best candidate
        if candidates:
            candidates.sort(key=lambda c: c["score"], reverse=True)
            best = candidates[0]
            
            result_slots.append({
                **slot,
                "suggested_employee_id": best["employee_id"],
                "suggested_employee_name": best["employee"]["name"],
            })
            
            # Add this assignment to the employee's shifts for future calculations
            employee_shift_map[best["employee_id"]].append({
                "employee_id": best["employee_id"],
                "start_at": slot_start,
                "end_at": slot_end,
                "call_time": slot_start,
            })
        else:
            # No suitable employee found
            result_slots.append({
                **slot,
                "suggested_employee_id": None,
                "unfilled_reason": "No available employee meets requirements",
            })
        
        explainability[slot_id] = {
            "rejections": rejections,
            "candidates_count": len(candidates),
        }
    
    # Calculate employee stats
    employee_stats = {}
    for emp in employees:
        emp_id = emp["employee_id"]
        emp_shifts = employee_shift_map[emp_id]
        
        # Filter to only shifts in the requested month
        from datetime import date
        month_start = date(year, month, 1)
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        month_end = date(year, month, last_day)
        
        month_shifts = [
            s for s in emp_shifts
            if (s.get("start_at") or s.get("call_time")).date() >= month_start
            and (s.get("start_at") or s.get("call_time")).date() <= month_end
        ]
        
        weekend_count = sum(
            1 for s in month_shifts
            if is_weekend_shift(s.get("start_at") or s.get("call_time"))
        )
        
        employee_stats[emp_id] = {
            "employee_id": emp_id,
            "employee_name": emp["name"],
            "total_shifts": len(month_shifts),
            "weekend_shifts": weekend_count,
        }
    
    return {
        "slots": result_slots,
        "explainability": explainability,
        "employee_stats": employee_stats,
    }
