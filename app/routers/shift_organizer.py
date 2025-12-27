"""
Shift Organizer API Router

Provides endpoints for:
- Viewing events and shifts for a month
- Generating shift suggestions
- Saving shift assignments
"""

import logging
from datetime import date, datetime
from typing import Optional
from calendar import monthrange

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.repositories import (
    EventRepository,
    EmployeeRepository,
    EmployeeShiftRepository,
    EmployeeUnavailabilityRepository,
    EmployeeUnavailabilityRulesRepository,
    EmployeeUnavailabilityExceptionsRepository,
)
from app.services.shift_generator import generate_shifts_for_events

router = APIRouter(prefix="/shift-organizer", tags=["shift-organizer"])
logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    org_id: int
    year: int
    month: int


class SlotData(BaseModel):
    event_id: int
    employee_id: Optional[int] = None
    start_at: datetime
    end_at: datetime
    shift_type: Optional[str] = None
    is_locked: bool = False
    shift_id: Optional[int] = None


class SaveRequest(BaseModel):
    org_id: int
    year: int
    month: int
    event_ids: Optional[list[int]] = None
    slots: list[SlotData]


@router.get("/month")
def get_month_data(org_id: int, year: int, month: int):
    """
    Get all data needed for shift organizer for a specific month.
    
    Returns:
    - events: list of events in the month
    - shifts: list of existing shifts
    - employees: list of active employees
    - employee_stats: shift counts per employee
    """
    try:
        # Validate month/year
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="Invalid month")
        if not (2020 <= year <= 2030):
            raise HTTPException(status_code=400, detail="Invalid year")
        
        # Get events for the month
        event_repo = EventRepository()
        all_events = event_repo.list_events_for_org(org_id)
        
        # Filter to requested month
        month_start = date(year, month, 1)
        _, last_day = monthrange(year, month)
        month_end = date(year, month, last_day)
        
        events = []
        for event in all_events:
            event_date = event["event_date"]
            if isinstance(event_date, str):
                event_date = date.fromisoformat(event_date)
            elif isinstance(event_date, datetime):
                event_date = event_date.date()
            
            if month_start <= event_date <= month_end:
                events.append(dict(event))
        
        # Get shifts for the month (including day before/after for calculations)
        shift_repo = EmployeeShiftRepository()
        shifts = shift_repo.get_shifts_for_month(org_id, year, month)
        
        # Get employees
        employee_repo = EmployeeRepository()
        employees = employee_repo.list_employees(org_id, active_only=True)
        
        # Calculate employee stats
        from app.services.shift_generator import is_weekend_shift
        
        employee_stats = {}
        for emp in employees:
            emp_id = emp["employee_id"]
            emp_shifts = [s for s in shifts if s["employee_id"] == emp_id]
            
            # Filter to month
            month_shifts = []
            for s in emp_shifts:
                shift_date = s.get("start_at") or s.get("call_time")
                if shift_date:
                    if isinstance(shift_date, str):
                        shift_date = datetime.fromisoformat(shift_date)
                    if shift_date.tzinfo is None:
                        from zoneinfo import ZoneInfo
                        shift_date = shift_date.replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
                    
                    if month_start <= shift_date.date() <= month_end:
                        month_shifts.append(s)
            
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
            "events": events,
            "shifts": shifts,
            "employees": employees,
            "employee_stats": list(employee_stats.values()),
        }
    
    except Exception as e:
        logger.error(f"Error getting month data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
def generate_shifts(request: GenerateRequest):
    """
    Generate shift suggestions for a month.
    
    Does NOT save to database - only returns suggestions.
    """
    try:
        org_id = request.org_id
        year = request.year
        month = request.month
        
        # Get all required data
        event_repo = EventRepository()
        all_events = event_repo.list_events_for_org(org_id)
        
        # Filter to requested month
        month_start = date(year, month, 1)
        _, last_day = monthrange(year, month)
        month_end = date(year, month, last_day)
        
        events = []
        for event in all_events:
            event_date = event["event_date"]
            if isinstance(event_date, str):
                event_date = date.fromisoformat(event_date)
            elif isinstance(event_date, datetime):
                event_date = event_date.date()
            
            if month_start <= event_date <= month_end:
                events.append(dict(event))
        
        # Get employees
        employee_repo = EmployeeRepository()
        employees = employee_repo.list_employees(org_id, active_only=True)
        
        # Get existing shifts
        shift_repo = EmployeeShiftRepository()
        existing_shifts = shift_repo.get_shifts_for_month(org_id, year, month)
        
        # Get unavailability
        unavail_repo = EmployeeUnavailabilityRepository()
        unavailability = unavail_repo.get_unavailability_for_month(org_id, year, month)
        
        # Generate shifts
        result = generate_shifts_for_events(
            events=events,
            employees=employees,
            existing_shifts=existing_shifts,
            unavailability=unavailability,
            org_id=org_id,
            year=year,
            month=month,
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error generating shifts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save")
def save_shifts(request: SaveRequest):
    """
    Save shift assignments to database.
    
    This performs upsert operations:
    - Creates new shifts
    - Updates existing shifts
    - Deletes shifts not in the request (unless locked)
    """
    try:
        org_id = request.org_id
        year = request.year
        month = request.month
        slots = request.slots
        
        shift_repo = EmployeeShiftRepository()
        
        # Get existing shifts for the month
        existing_shifts = shift_repo.get_shifts_for_month(org_id, year, month)
        
        # Build map of event_id -> shifts
        event_shift_map = {}
        for shift in existing_shifts:
            event_id = shift["event_id"]
            if event_id not in event_shift_map:
                event_shift_map[event_id] = []
            event_shift_map[event_id].append(shift)
        
        # Process slots
        saved_shift_ids = set()
        
        for slot in slots:
            if not slot.employee_id:
                # No employee assigned - skip
                continue
            
            # Upsert shift
            shift_id = shift_repo.upsert_shift(
                org_id=org_id,
                event_id=slot.event_id,
                employee_id=slot.employee_id,
                start_at=slot.start_at,
                end_at=slot.end_at,
                shift_type=slot.shift_type,
                is_locked=slot.is_locked,
                shift_id=slot.shift_id,
            )
            saved_shift_ids.add(shift_id)
        
        # Delete shifts that are not in the saved list and not locked
        # (Only for events that have slots in the request)
        events_in_request = set(request.event_ids or []) | set(slot.event_id for slot in slots)
        
        for event_id in events_in_request:
            existing = event_shift_map.get(event_id, [])
            for shift in existing:
                shift_id = shift["shift_id"]
                is_locked = shift.get("is_locked", False)
                
                if shift_id not in saved_shift_ids and not is_locked:
                    # Delete this shift
                    shift_repo.delete_shift(org_id, shift_id)
        
        # Return updated data
        return get_month_data(org_id, year, month)
    
    except Exception as e:
        logger.error(f"Error saving shifts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events/{event_id}/unavailable-employees")
def get_unavailable_employees(event_id: int, org_id: int, debug: bool = False):
    """
    Get list of employees who are unavailable for a specific event.
    
    Args:
        event_id: Event to check
        org_id: Organization ID
        debug: If true, returns detailed source info (rule IDs, window calculations)
    
    Returns:
        List of unavailable employees with conflict details
    """
    try:
        from app.services.recurring_availability import check_event_conflicts, expand_rule_for_month, merge_unavailability
        from calendar import monthrange
        
        # Get event details
        event_repo = EventRepository()
        event = event_repo.get_event_by_id(org_id, event_id)
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Get event date to determine which month to query
        event_date = event["event_date"]
        if isinstance(event_date, str):
            event_date = date.fromisoformat(event_date)
        elif isinstance(event_date, datetime):
            event_date = event_date.date()
        
        year = event_date.year
        month = event_date.month
        
        # Get all employees
        employee_repo = EmployeeRepository()
        employees = employee_repo.list_employees(org_id, active_only=True)
        
        # Get unavailability data for this month
        unavail_repo = EmployeeUnavailabilityRepository()
        manual_entries = unavail_repo.get_unavailability_for_month(org_id, year, month)
        
        # Mark manual entries
        for entry in manual_entries:
            if not entry.get("source_type"):
                entry["source_type"] = "manual"
        
        # Get rules and expand
        rules_repo = EmployeeUnavailabilityRulesRepository()
        rules = rules_repo.get_active_rules_for_month(org_id, year, month)
        
        # Get exceptions
        rule_ids = [r["rule_id"] for r in rules]
        exceptions_repo = EmployeeUnavailabilityExceptionsRepository()
        exceptions_by_rule = exceptions_repo.get_exceptions_for_rules(rule_ids) if rule_ids else {}
        
        # Expand rules
        rule_entries = []
        for rule in rules:
            rule_id = rule["rule_id"]
            exceptions = exceptions_by_rule.get(rule_id, [])
            
            occurrences = expand_rule_for_month(rule, year, month, exceptions)
            
            for occ in occurrences:
                occ["employee_id"] = rule["employee_id"]
                occ["employee_name"] = rule["employee_name"]
            
            rule_entries.extend(occurrences)
        
        # Group unavailability by employee
        unavail_by_employee = {}
        for entry in manual_entries + rule_entries:
            emp_id = entry["employee_id"]
            if emp_id not in unavail_by_employee:
                unavail_by_employee[emp_id] = []
            unavail_by_employee[emp_id].append(entry)
        
        # Merge for each employee and check conflicts
        conflicts = []
        for emp in employees:
            emp_id = emp["employee_id"]
            emp_unavail = unavail_by_employee.get(emp_id, [])
            
            if not emp_unavail:
                continue
            
            # Separate manual and rule entries
            manual = [e for e in emp_unavail if e.get("source_type") == "manual"]
            rules_emp = [e for e in emp_unavail if e.get("source_type") == "rule"]
            
            # Merge with precedence
            merged = merge_unavailability(manual, rules_emp)
            
            # Check for conflict
            conflict = check_event_conflicts(event, emp_id, merged)
            
            if conflict:
                conflict_data = {
                    "employee_id": emp_id,
                    "employee_name": emp["name"],
                    "unavail_start": conflict["unavail_start"].isoformat(),
                    "unavail_end": conflict["unavail_end"].isoformat(),
                    "note": conflict["note"],
                }
                
                if debug:
                    conflict_data["debug"] = {
                        "source_type": conflict["source_type"],
                        "source_rule_id": conflict.get("source_rule_id"),
                        "event_start": conflict["event_start"].isoformat(),
                        "event_end": conflict["event_end"].isoformat(),
                        "load_in_time": str(event.get("load_in_time")),
                        "show_time": str(event.get("show_time")),
                    }
                
                conflicts.append(conflict_data)
        
        return {
            "event_id": event_id,
            "event_name": event["name"],
            "event_date": str(event_date),
            "unavailable_employees": conflicts,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking unavailable employees: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
