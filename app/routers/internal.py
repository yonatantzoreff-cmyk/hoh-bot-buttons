"""Internal API endpoints."""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.services.scheduler import SchedulerService
from app.utils.env import get_scheduler_token, is_scheduler_token_configured
from app.diagnostics.scheduler import run_scheduler_diagnostics

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
    org_id: Optional[int] = None
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


@router.get("/diagnostics/scheduler")
async def get_scheduler_diagnostics(
    _verified: bool = Depends(verify_scheduler_token),
    org_id: Optional[int] = Query(None, description="Organization ID to focus diagnostics on")
):
    """
    Run comprehensive scheduler diagnostics to troubleshoot visibility issues.
    
    This endpoint performs a series of checks to diagnose why scheduled messages
    may not be visible in the UI/API:
    - Database connection and fingerprint
    - Schema existence and structure
    - Data visibility (row counts, filtering)
    - Organization scoping
    - Endpoint query simulation
    - Fetch logic diagnostics
    - Timezone configuration
    
    Args:
        org_id: Optional organization ID to focus on for scoping checks
    
    Returns:
        JSON with structured diagnostic report including:
        - summary: Suspected root cause, confidence, key evidence
        - checks: Detailed results of each diagnostic check
        - recommendations: Prioritized list of fixes
    
    Authentication:
        Requires Bearer token via SCHEDULER_RUN_TOKEN environment variable
        
    Example:
        curl -H "Authorization: Bearer <token>" \\
             "https://<host>/internal/diagnostics/scheduler?org_id=1"
    """
    try:
        report = run_scheduler_diagnostics(org_id=org_id)
        return JSONResponse(content=report, status_code=200)
    except Exception as e:
        logger.error(f"Scheduler diagnostics failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Diagnostics execution failed: {str(e)}"
        )
