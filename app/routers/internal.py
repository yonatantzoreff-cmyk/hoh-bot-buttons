"""
Internal API endpoints for system operations.
These endpoints are protected and meant to be called by internal services or scheduled jobs.
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.services import scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def get_scheduler_token() -> Optional[str]:
    """
    Safely retrieve the scheduler token from environment.
    Returns None if not configured.
    """
    return os.getenv("SCHEDULER_RUN_TOKEN")


def verify_scheduler_token(authorization: str = Header(None)) -> None:
    """
    Verify the scheduler authorization token.
    
    Args:
        authorization: Authorization header (expected format: "Bearer <token>")
    
    Raises:
        HTTPException: 500 if token not configured, 401 if missing or invalid
    """
    token = get_scheduler_token()
    
    # Check if token is configured
    if not token:
        logger.error("SCHEDULER_RUN_TOKEN not configured in environment")
        raise HTTPException(
            status_code=500,
            detail="Scheduler token not configured"
        )
    
    # Check if authorization header is provided
    if not authorization:
        logger.warning("Scheduler endpoint called without Authorization header")
        raise HTTPException(
            status_code=401,
            detail="Authorization header required"
        )
    
    # Parse Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("Scheduler endpoint called with invalid Authorization format")
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization format. Expected: Bearer <token>"
        )
    
    provided_token = parts[1]
    
    # Verify token matches
    if provided_token != token:
        logger.warning("Scheduler endpoint called with invalid token")
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization token"
        )


@router.post("/run-scheduler")
def run_scheduler(
    authorization: str = Header(None),
    org_id: Optional[int] = Query(None, description="Optional organization ID to limit processing"),
):
    """
    Manually trigger the scheduler to process due reminders.
    
    This endpoint is protected by Bearer token authentication.
    The token must be provided in the Authorization header as "Bearer <token>".
    The token must match the SCHEDULER_RUN_TOKEN environment variable.
    
    Args:
        authorization: Authorization header with Bearer token
        org_id: Optional organization ID to limit processing to a single org
    
    Returns:
        JSON with counters:
        - due_found: Number of items found that are due
        - sent: Number successfully sent
        - failed: Number that failed
        - skipped: Number skipped
        - blocked: Number blocked
        - postponed: Number postponed
        - duration_ms: Time taken in milliseconds
    
    Raises:
        HTTPException: 401 if authorization fails, 500 if token not configured
    """
    # Verify authentication
    verify_scheduler_token(authorization)
    
    # Run the scheduler
    logger.info(f"Scheduler endpoint called (org_id={org_id})")
    
    try:
        result = scheduler.run_once(org_id=org_id)
        return result
    except Exception as e:
        logger.error(f"Scheduler run failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Scheduler run failed: {str(e)}"
        )
