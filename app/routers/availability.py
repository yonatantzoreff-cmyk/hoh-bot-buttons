"""
Employee Availability API Router

Provides endpoints for managing employee unavailability blocks.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.repositories import EmployeeUnavailabilityRepository

router = APIRouter(prefix="/availability", tags=["availability"])
logger = logging.getLogger(__name__)


class CreateUnavailabilityRequest(BaseModel):
    org_id: int
    employee_id: int
    start_at: datetime
    end_at: datetime
    note: Optional[str] = None


@router.get("/month")
def get_month_unavailability(org_id: int, year: int, month: int):
    """
    Get all unavailability blocks for a month.
    """
    try:
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="Invalid month")
        if not (2020 <= year <= 2030):
            raise HTTPException(status_code=400, detail="Invalid year")
        
        repo = EmployeeUnavailabilityRepository()
        unavailability = repo.get_unavailability_for_month(org_id, year, month)
        
        return {
            "unavailability": unavailability,
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
