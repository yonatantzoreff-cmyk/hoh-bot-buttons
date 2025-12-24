"""Internal API endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

from app.services.scheduler import SchedulerService
from app.utils.env import get_scheduler_token, is_scheduler_token_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_scheduler_token(authorization: Annotated[str, Header()] = None):
    """
    Verify the scheduler token from Authorization header.
    
    Raises:
        HTTPException: 500 if token not configured, 401 if invalid/missing.
    """
    # Check if token is configured
    if not is_scheduler_token_configured():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scheduler token not configured"
        )
    
    # Check if Authorization header is provided
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )
    
    # Extract token from Bearer scheme
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected 'Bearer <token>'"
        )
    
    provided_token = parts[1]
    expected_token = get_scheduler_token()
    
    # Verify token
    if provided_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    return True


@router.post("/run-scheduler")
async def run_scheduler(
    _verified: bool = Depends(verify_scheduler_token),
    org_id: int = None
):
    """
    Run the scheduler once for all orgs or a specific org.
    
    Args:
        org_id: Optional organization ID to run for. If not provided, runs for all orgs.
    
    Returns:
        JSON with counters: due_found, sent, failed, skipped, blocked, postponed, duration_ms
    """
    scheduler = SchedulerService()
    result = await scheduler.run_once(org_id=org_id)
    
    return JSONResponse(result)
