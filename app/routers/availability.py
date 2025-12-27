"""
Employee Availability API Router

Provides endpoints for managing employee unavailability blocks.
Supports both one-time manual entries and recurring rules.
"""

import logging
from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.repositories import (
    EmployeeUnavailabilityRepository,
    EmployeeUnavailabilityRulesRepository,
    EmployeeUnavailabilityExceptionsRepository,
)
from app.services.recurring_availability import expand_rule_for_month, merge_unavailability

router = APIRouter(prefix="/availability", tags=["availability"])
logger = logging.getLogger(__name__)


class CreateUnavailabilityRequest(BaseModel):
    org_id: int
    employee_id: int
    start_at: datetime
    end_at: datetime
    note: Optional[str] = None


@router.get("/month")
def get_month_unavailability(org_id: int, year: int, month: int, employee_id: Optional[int] = None):
    """
    Get all unavailability blocks for a month.
    
    Returns merged view of:
    - Manual entries (from employee_unavailability)
    - Rule-generated occurrences (from employee_unavailability_rules)
    - Minus exceptions (from employee_unavailability_exceptions)
    
    Each entry includes source info for debugging.
    """
    try:
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="Invalid month")
        if not (2020 <= year <= 2030):
            raise HTTPException(status_code=400, detail="Invalid year")
        
        # Get manual entries
        unavail_repo = EmployeeUnavailabilityRepository()
        manual_entries = unavail_repo.get_unavailability_for_month(org_id, year, month)
        
        # Filter by employee if specified
        if employee_id:
            manual_entries = [e for e in manual_entries if e["employee_id"] == employee_id]
        
        # Mark manual entries
        for entry in manual_entries:
            if not entry.get("source_type"):
                entry["source_type"] = "manual"
        
        # Get active rules for this month
        rules_repo = EmployeeUnavailabilityRulesRepository()
        rules = rules_repo.get_active_rules_for_month(org_id, year, month)
        
        # Filter by employee if specified
        if employee_id:
            rules = [r for r in rules if r["employee_id"] == employee_id]
        
        # Get exceptions for all rules
        rule_ids = [r["rule_id"] for r in rules]
        exceptions_repo = EmployeeUnavailabilityExceptionsRepository()
        exceptions_by_rule = exceptions_repo.get_exceptions_for_rules(rule_ids) if rule_ids else {}
        
        # Expand each rule
        rule_entries = []
        for rule in rules:
            rule_id = rule["rule_id"]
            exceptions = exceptions_by_rule.get(rule_id, [])
            
            occurrences = expand_rule_for_month(rule, year, month, exceptions)
            
            # Add employee info to each occurrence
            for occ in occurrences:
                occ["employee_id"] = rule["employee_id"]
                occ["employee_name"] = rule["employee_name"]
                occ["unavailability_id"] = None  # Rule entries don't have unavailability_id
            
            rule_entries.extend(occurrences)
        
        # Merge with precedence (manual overrides rule on same date)
        merged = merge_unavailability(manual_entries, rule_entries)
        
        return {
            "unavailability": merged,
            "rules": rules,  # Include rules metadata for UI
        }
    
    except Exception as e:
        logger.error(f"Error getting unavailability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
def create_unavailability(request: CreateUnavailabilityRequest):
    """
    Create a new unavailability block.
    """
    try:
        repo = EmployeeUnavailabilityRepository()
        
        unavailability_id = repo.create_unavailability(
            org_id=request.org_id,
            employee_id=request.employee_id,
            start_at=request.start_at,
            end_at=request.end_at,
            note=request.note,
        )
        
        return {
            "unavailability_id": unavailability_id,
            "message": "Unavailability block created successfully",
        }
    
    except Exception as e:
        logger.error(f"Error creating unavailability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{unavailability_id}")
def delete_unavailability(unavailability_id: int, org_id: int):
    """
    Delete an unavailability block.
    """
    try:
        repo = EmployeeUnavailabilityRepository()
        repo.delete_unavailability(org_id, unavailability_id)
        
        return {
            "message": "Unavailability block deleted successfully",
        }
    
    except Exception as e:
        logger.error(f"Error deleting unavailability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===========================
#  RECURRING RULES ENDPOINTS
# ===========================

class CreateRuleRequest(BaseModel):
    org_id: int
    employee_id: int
    pattern: str  # 'weekly', 'biweekly', 'monthly'
    start_date: date
    anchor_date: Optional[date] = None
    days_of_week: Optional[List[int]] = None
    day_of_month: Optional[int] = None
    all_day: bool = False
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    notes: Optional[str] = None
    until_date: Optional[date] = None


@router.post("/rules")
def create_rule(request: CreateRuleRequest):
    """
    Create a recurring unavailability rule.
    """
    try:
        from datetime import time
        
        # Parse times if provided
        start_time = None
        end_time = None
        if request.start_time:
            start_time = time.fromisoformat(request.start_time)
        if request.end_time:
            end_time = time.fromisoformat(request.end_time)
        
        # Validate pattern-specific fields
        if request.pattern in ["weekly", "biweekly"]:
            if not request.days_of_week:
                raise HTTPException(status_code=400, detail="days_of_week required for weekly/biweekly")
        elif request.pattern == "monthly":
            if not request.day_of_month:
                raise HTTPException(status_code=400, detail="day_of_month required for monthly")
        else:
            raise HTTPException(status_code=400, detail="Invalid pattern")
        
        # Validate time requirements
        if not request.all_day and (not start_time or not end_time):
            raise HTTPException(status_code=400, detail="start_time and end_time required when all_day=false")
        
        repo = EmployeeUnavailabilityRulesRepository()
        rule_id = repo.create_rule(
            org_id=request.org_id,
            employee_id=request.employee_id,
            pattern=request.pattern,
            start_date=request.start_date,
            anchor_date=request.anchor_date,
            days_of_week=request.days_of_week,
            day_of_month=request.day_of_month,
            all_day=request.all_day,
            start_time=start_time,
            end_time=end_time,
            notes=request.notes,
            until_date=request.until_date,
        )
        
        return {
            "rule_id": rule_id,
            "message": "Recurring rule created successfully",
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, org_id: int):
    """
    Delete a recurring unavailability rule.
    This will also delete all exceptions for this rule (cascade).
    """
    try:
        repo = EmployeeUnavailabilityRulesRepository()
        repo.delete_rule(org_id, rule_id)
        
        return {
            "message": "Rule deleted successfully",
        }
    
    except Exception as e:
        logger.error(f"Error deleting rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===========================
#  EXCEPTIONS ENDPOINTS
# ===========================

class CreateExceptionRequest(BaseModel):
    rule_id: int
    date: date


@router.post("/exceptions")
def create_exception(request: CreateExceptionRequest):
    """
    Create an exception for a recurring rule on a specific date.
    This cancels the rule occurrence on that date.
    """
    try:
        repo = EmployeeUnavailabilityExceptionsRepository()
        exception_id = repo.create_exception(
            rule_id=request.rule_id,
            exception_date=request.date,
        )
        
        return {
            "exception_id": exception_id,
            "message": "Exception created successfully",
        }
    
    except Exception as e:
        logger.error(f"Error creating exception: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/exceptions/{exception_id}")
def delete_exception(exception_id: int):
    """
    Delete an exception (re-enables the rule occurrence on that date).
    """
    try:
        repo = EmployeeUnavailabilityExceptionsRepository()
        repo.delete_exception(exception_id)
        
        return {
            "message": "Exception deleted successfully",
        }
    
    except Exception as e:
        logger.error(f"Error deleting exception: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
