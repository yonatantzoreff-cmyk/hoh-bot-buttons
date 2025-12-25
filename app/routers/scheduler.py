"""Scheduler API routes for viewing and managing scheduled messages."""

import logging
from typing import Optional, List
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService
from app.repositories import (
    ScheduledMessageRepository,
    SchedulerSettingsRepository,
    EventRepository,
    ContactRepository,
    EmployeeRepository,
    EmployeeShiftRepository,
)
from app.time_utils import now_utc, utc_to_local_datetime
from app.services.scheduler import SchedulerService
from app.services.scheduler_job_builder import (
    build_or_update_jobs_for_event,
    build_or_update_jobs_for_shifts,
)
from app.appdb import get_session

router = APIRouter()
logger = logging.getLogger(__name__)


class SchedulerSettingsUpdate(BaseModel):
    """Model for updating scheduler settings."""
    enabled_global: Optional[bool] = None
    enabled_init: Optional[bool] = None
    enabled_tech: Optional[bool] = None
    enabled_shift: Optional[bool] = None


class SendNowResponse(BaseModel):
    """Response for send-now action."""
    success: bool
    message: str


@router.get("/api/scheduler/jobs")
async def list_scheduler_jobs(
    org_id: int = Query(1, description="Organization ID"),
    message_type: Optional[str] = Query(None, description="Filter by message type: INIT, TECH_REMINDER, SHIFT_REMINDER"),
    hide_sent: bool = Query(False, description="Hide sent messages"),
    show_past: bool = Query(False, description="Show past messages (send_at < now or completed status)"),
) -> List[dict]:
    """
    List scheduled message jobs with full context for UI display.
    
    Returns enriched job data including:
    - Event details (name, date, show_time, load_in_time)
    - Producer and technician contact info
    - Resolved recipient info
    - Status and timing information
    """
    scheduled_repo = ScheduledMessageRepository()
    events_repo = EventRepository()
    contacts_repo = ContactRepository()
    employees_repo = EmployeeRepository()
    
    # Build query to get all scheduled messages for this org
    query = """
        SELECT 
            sm.*,
            e.name as event_name,
            e.event_date,
            e.show_time,
            e.load_in_time,
            e.producer_contact_id,
            e.technical_contact_id,
            es.call_time as shift_call_time
        FROM scheduled_messages sm
        LEFT JOIN events e ON sm.event_id = e.event_id
        LEFT JOIN employee_shifts es ON sm.shift_id = es.shift_id
        WHERE sm.org_id = :org_id
    """
    
    params = {"org_id": org_id}
    
    # Apply message_type filter
    if message_type:
        query += " AND sm.message_type = :message_type"
        params["message_type"] = message_type
    
    # Apply hide_sent filter
    if hide_sent:
        query += " AND sm.status != 'sent'"
    
    # Apply show_past filter (default is to hide past)
    if not show_past:
        # Hide past jobs: send_at < now OR status in completed states
        query += " AND (sm.send_at >= :now OR sm.status NOT IN ('sent', 'failed', 'skipped'))"
        params["now"] = now_utc()
    
    query += " ORDER BY sm.send_at ASC"
    
    with get_session() as session:
        result = session.execute(text(query), params)
        rows = [dict(row._mapping) for row in result]
    
    # Enrich each job with additional details
    enriched_jobs = []
    for job in rows:
        enriched_job = dict(job)
        
        # Get producer and technician contacts
        if job.get("producer_contact_id"):
            producer = contacts_repo.get_contact_by_id(org_id, job["producer_contact_id"])
            enriched_job["producer_name"] = producer.get("name") if producer else None
            enriched_job["producer_phone"] = producer.get("phone") if producer else None
        else:
            enriched_job["producer_name"] = None
            enriched_job["producer_phone"] = None
        
        if job.get("technical_contact_id"):
            technical = contacts_repo.get_contact_by_id(org_id, job["technical_contact_id"])
            enriched_job["technical_name"] = technical.get("name") if technical else None
            enriched_job["technical_phone"] = technical.get("phone") if technical else None
        else:
            enriched_job["technical_name"] = None
            enriched_job["technical_phone"] = None
        
        # Resolve recipient preview (same logic as scheduler service)
        recipient_info = _preview_recipient(job, org_id, events_repo, contacts_repo, employees_repo)
        enriched_job["recipient_name"] = recipient_info.get("name")
        enriched_job["recipient_phone"] = recipient_info.get("phone")
        enriched_job["recipient_missing"] = not recipient_info.get("success")
        
        enriched_jobs.append(enriched_job)
    
    return enriched_jobs


@router.post("/api/scheduler/jobs/{job_id}/enable")
async def toggle_job_enabled(
    job_id: int,
    enabled: bool = Query(..., description="Enable or disable the job"),
    org_id: int = Query(1, description="Organization ID"),
) -> dict:
    """Enable or disable a scheduled message job."""
    scheduled_repo = ScheduledMessageRepository()
    
    # Get the job first to verify it exists and belongs to this org
    job = scheduled_repo.get_scheduled_message(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Job does not belong to this organization")
    
    # Update the enabled status
    scheduled_repo.set_enabled(job_id, enabled)
    
    return {
        "success": True,
        "job_id": job_id,
        "enabled": enabled,
    }


@router.post("/api/scheduler/jobs/{job_id}/send-now")
async def send_job_now(
    job_id: int,
    org_id: int = Query(1, description="Organization ID"),
) -> SendNowResponse:
    """Send a scheduled message immediately."""
    scheduled_repo = ScheduledMessageRepository()
    settings_repo = SchedulerSettingsRepository()
    
    # Get the job first to verify it exists and belongs to this org
    job = scheduled_repo.get_scheduled_message(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Job does not belong to this organization")
    
    # Check if job is in a sendable state
    status = job.get("status")
    if status in ("sent", "failed"):
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot send job with status '{status}'"
        )
    
    # Process the job using the scheduler service
    # Note: We call the internal _process_job method directly here.
    # TODO: Consider refactoring to use a public method in SchedulerService
    # or extracting this logic to a shared module for better encapsulation.
    scheduler = SchedulerService()
    settings = settings_repo.get_or_create_settings(org_id)
    now = now_utc()
    
    try:
        result = await scheduler._process_job(job, settings, now)
        
        if result == "sent":
            return SendNowResponse(success=True, message="Message sent successfully")
        elif result == "blocked":
            return SendNowResponse(success=False, message="Message blocked: recipient missing")
        elif result == "failed":
            return SendNowResponse(success=False, message="Failed to send message")
        elif result == "skipped":
            return SendNowResponse(success=False, message="Message skipped")
        elif result == "postponed":
            return SendNowResponse(success=False, message="Message postponed due to weekend rule")
        else:
            return SendNowResponse(success=False, message=f"Unknown result: {result}")
            
    except Exception as e:
        logger.error(f"Error sending job {job_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/scheduler/settings")
async def get_scheduler_settings(
    org_id: int = Query(1, description="Organization ID"),
) -> dict:
    """Get scheduler settings for an organization."""
    settings_repo = SchedulerSettingsRepository()
    settings = settings_repo.get_or_create_settings(org_id)
    return settings


@router.put("/api/scheduler/settings")
async def update_scheduler_settings(
    settings: SchedulerSettingsUpdate,
    org_id: int = Query(1, description="Organization ID"),
) -> dict:
    """Update scheduler settings for an organization."""
    settings_repo = SchedulerSettingsRepository()
    
    # Only update fields that were provided
    update_kwargs = {}
    if settings.enabled_global is not None:
        update_kwargs["enabled_global"] = settings.enabled_global
    if settings.enabled_init is not None:
        update_kwargs["enabled_init"] = settings.enabled_init
    if settings.enabled_tech is not None:
        update_kwargs["enabled_tech"] = settings.enabled_tech
    if settings.enabled_shift is not None:
        update_kwargs["enabled_shift"] = settings.enabled_shift
    
    if update_kwargs:
        settings_repo.update_settings(org_id, **update_kwargs)
    
    # Return updated settings
    return settings_repo.get_or_create_settings(org_id)


class SkippedJobSample(BaseModel):
    """Sample of a skipped job for debugging."""
    event_id: int
    event_name: str
    message_type: str
    reason: str
    count: Optional[int] = None  # For shift aggregations


class FetchResponse(BaseModel):
    """Response for fetch action."""
    success: bool
    message: str
    events_scanned: int
    shifts_scanned: int
    jobs_created: int
    jobs_updated: int
    jobs_blocked: int
    jobs_skipped: int = 0
    skipped_reasons: dict[str, int] = {}
    skipped_samples: list[SkippedJobSample] = []
    errors_count: int = 0
    errors: list[str] = []


@router.post("/api/scheduler/fetch")
async def fetch_future_events(
    org_id: int = Query(1, description="Organization ID"),
) -> FetchResponse:
    """
    Fetch and synchronize all future events into scheduled_messages.
    
    This endpoint:
    1. Queries all future events (event_date >= today in Israel time)
    2. For each event, creates/updates INIT and TECH_REMINDER jobs
    3. For each event, creates/updates SHIFT_REMINDER jobs for all shifts
    4. Returns counts of operations performed and any errors encountered
    5. Tracks skip reasons and samples for debugging
    
    This operation is idempotent - running it multiple times won't create duplicates.
    """
    try:
        events_repo = EventRepository()
        
        # Get all future events
        future_events = events_repo.list_future_events_for_org(org_id)
        events_scanned = len(future_events)
        
        jobs_created = 0
        jobs_updated = 0
        jobs_blocked = 0
        jobs_skipped = 0
        shifts_scanned = 0
        errors = []
        
        # Track skip reasons
        skipped_reasons = {}
        skipped_samples = []
        MAX_SKIP_SAMPLES = 10
        
        logger.info(f"Fetching scheduler jobs for {events_scanned} future events (org_id={org_id})")
        
        for event in future_events:
            event_id = event["event_id"]
            event_name = event.get("name", f"event_{event_id}")
            
            # Track counts for this event
            event_created = 0
            event_updated = 0
            event_blocked = 0
            event_skipped = 0
            
            try:
                # Build/update event-based jobs (INIT + TECH_REMINDER)
                event_result = build_or_update_jobs_for_event(org_id, event_id)
                
                # Count jobs created/updated/blocked/skipped for this event
                if event_result.get("init_status") == "created":
                    jobs_created += 1
                    event_created += 1
                elif event_result.get("init_status") == "updated":
                    jobs_updated += 1
                    event_updated += 1
                elif event_result.get("init_status") == "blocked":
                    jobs_blocked += 1
                    event_blocked += 1
                elif event_result.get("init_status") == "skipped":
                    jobs_skipped += 1
                    event_skipped += 1
                    skip_reason = event_result.get("init_skip_reason", "unknown")
                    skipped_reasons[skip_reason] = skipped_reasons.get(skip_reason, 0) + 1
                    
                    # Add to samples if under limit
                    if len(skipped_samples) < MAX_SKIP_SAMPLES:
                        skipped_samples.append(SkippedJobSample(
                            event_id=event_id,
                            event_name=event_name,
                            message_type="INIT",
                            reason=skip_reason
                        ))
                
                if event_result.get("tech_status") == "created":
                    jobs_created += 1
                    event_created += 1
                elif event_result.get("tech_status") == "updated":
                    jobs_updated += 1
                    event_updated += 1
                elif event_result.get("tech_status") == "blocked":
                    jobs_blocked += 1
                    event_blocked += 1
                elif event_result.get("tech_status") == "skipped":
                    jobs_skipped += 1
                    event_skipped += 1
                    skip_reason = event_result.get("tech_skip_reason", "unknown")
                    skipped_reasons[skip_reason] = skipped_reasons.get(skip_reason, 0) + 1
                    
                    # Add to samples if under limit
                    if len(skipped_samples) < MAX_SKIP_SAMPLES:
                        skipped_samples.append(SkippedJobSample(
                            event_id=event_id,
                            event_name=event_name,
                            message_type="TECH_REMINDER",
                            reason=skip_reason
                        ))
                
                # Build/update shift-based jobs (SHIFT_REMINDER)
                shifts_result = build_or_update_jobs_for_shifts(org_id, event_id)
                
                if not shifts_result.get("disabled"):
                    shifts_scanned += shifts_result.get("processed_count", 0)
                    shift_created = shifts_result.get("created", 0)
                    shift_updated = shifts_result.get("updated", 0)
                    shift_blocked = shifts_result.get("blocked", 0)
                    shift_skipped = shifts_result.get("skipped", 0)
                    
                    jobs_created += shift_created
                    jobs_updated += shift_updated
                    jobs_blocked += shift_blocked
                    jobs_skipped += shift_skipped
                    
                    event_created += shift_created
                    event_updated += shift_updated
                    event_blocked += shift_blocked
                    event_skipped += shift_skipped
                    
                    # Add shift skip reasons
                    shift_skip_reasons = shifts_result.get("skip_reasons", {})
                    for reason, count in shift_skip_reasons.items():
                        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + count
                        
                        # Add samples for shift skips (simplified - we don't have individual shift details here)
                        if len(skipped_samples) < MAX_SKIP_SAMPLES and count > 0:
                            skipped_samples.append(SkippedJobSample(
                                event_id=event_id,
                                event_name=event_name,
                                message_type="SHIFT_REMINDER",
                                reason=reason,
                                count=count
                            ))
                
                # Log detailed results for this event
                logger.info(
                    f"scheduler fetch: event_id={event_id}, name='{event_name}', "
                    f"created={event_created}, updated={event_updated}, blocked={event_blocked}, skipped={event_skipped}"
                )
                    
            except Exception as e:
                error_msg = f"Event {event_id} ('{event_name}'): {type(e).__name__}: {str(e)}"
                logger.error(f"Error building jobs for event {event_id}: {e}", exc_info=True)
                errors.append(error_msg)
        
        # Limit errors to first 10 in response
        errors_to_return = errors[:10]
        errors_count = len(errors)
        
        message = f"Synced {events_scanned} events and {shifts_scanned} shifts"
        if errors_count > 0:
            message += f" ({errors_count} error(s))"
        
        logger.info(
            f"Fetch complete: events_scanned={events_scanned}, shifts_scanned={shifts_scanned}, "
            f"jobs_created={jobs_created}, jobs_updated={jobs_updated}, jobs_blocked={jobs_blocked}, "
            f"jobs_skipped={jobs_skipped}, errors_count={errors_count}"
        )
        
        return FetchResponse(
            success=True,
            message=message,
            events_scanned=events_scanned,
            shifts_scanned=shifts_scanned,
            jobs_created=jobs_created,
            jobs_updated=jobs_updated,
            jobs_blocked=jobs_blocked,
            jobs_skipped=jobs_skipped,
            skipped_reasons=skipped_reasons,
            skipped_samples=skipped_samples,
            errors_count=errors_count,
            errors=errors_to_return,
        )
        
    except Exception as e:
        logger.error(f"Error in fetch_future_events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class CleanupResponse(BaseModel):
    """Response for cleanup action."""
    success: bool
    message: str
    deleted_count: int


@router.delete("/api/scheduler/past-logs")
async def cleanup_past_logs(
    org_id: int = Query(1, description="Organization ID"),
    days: int = Query(30, description="Delete logs older than this many days"),
) -> CleanupResponse:
    """
    Delete old scheduler logs to keep the database clean.
    
    Deletes scheduled_messages where:
    - status IN (sent, failed, skipped) 
    - AND send_at < now - {days} days
    
    This only removes completed jobs that are old. It will not delete:
    - Future scheduled jobs
    - Jobs in 'scheduled', 'retrying', or 'blocked' status
    """
    try:
        # Calculate cutoff date
        now = now_utc()
        cutoff_date = now - timedelta(days=days)
        
        # Delete old completed jobs
        query = text("""
            DELETE FROM scheduled_messages
            WHERE org_id = :org_id
              AND status IN ('sent', 'failed', 'skipped')
              AND send_at < :cutoff_date
        """)
        
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id, "cutoff_date": cutoff_date})
            deleted_count = result.rowcount
        
        message = f"Deleted {deleted_count} old log entries"
        logger.info(f"Cleanup complete for org {org_id}: deleted {deleted_count} logs older than {days} days")
        
        return CleanupResponse(
            success=True,
            message=message,
            deleted_count=deleted_count,
        )
        
    except Exception as e:
        logger.error(f"Error in cleanup_past_logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _preview_recipient(
    job: dict, 
    org_id: int,
    events_repo: EventRepository,
    contacts_repo: ContactRepository,
    employees_repo: EmployeeRepository,
) -> dict:
    """
    Preview the recipient for a job (same logic as scheduler service).
    
    Returns:
        Dict with: success (bool), name (str), phone (str), error (str)
    """
    message_type = job.get("message_type")
    event_id = job.get("event_id")
    shift_id = job.get("shift_id")
    
    if message_type == "INIT":
        # INIT: If event.technical_phone exists -> recipient=technician, else producer
        event = events_repo.get_event_by_id(org_id, event_id)
        if not event:
            return {"success": False, "error": "Event not found"}
        
        # Try technical contact first
        technical_contact_id = event.get("technical_contact_id")
        if technical_contact_id:
            technical = contacts_repo.get_contact_by_id(org_id, technical_contact_id)
            if technical:
                tech_phone = technical.get("phone")
                if tech_phone and tech_phone.strip():
                    return {
                        "success": True,
                        "phone": tech_phone,
                        "name": technical.get("name", ""),
                    }
        
        # Fallback to producer
        producer_contact_id = event.get("producer_contact_id")
        if producer_contact_id:
            producer = contacts_repo.get_contact_by_id(org_id, producer_contact_id)
            if producer:
                prod_phone = producer.get("phone")
                if prod_phone and prod_phone.strip():
                    return {
                        "success": True,
                        "phone": prod_phone,
                        "name": producer.get("name", ""),
                    }
        
        return {"success": False, "error": "Missing phone number"}
    
    elif message_type == "TECH_REMINDER":
        # TECH_REMINDER: event.technical_phone
        event = events_repo.get_event_by_id(org_id, event_id)
        if not event:
            return {"success": False, "error": "Event not found"}
        
        technical_contact_id = event.get("technical_contact_id")
        if not technical_contact_id:
            return {"success": False, "error": "Technical contact not assigned"}
        
        technical = contacts_repo.get_contact_by_id(org_id, technical_contact_id)
        if not technical:
            return {"success": False, "error": "Technical contact not found"}
        
        tech_phone = technical.get("phone")
        if not tech_phone or not tech_phone.strip():
            return {"success": False, "error": "Technical contact phone missing"}
        
        return {
            "success": True,
            "phone": tech_phone,
            "name": technical.get("name", ""),
        }
    
    elif message_type == "SHIFT_REMINDER":
        # SHIFT_REMINDER: shift.employee_phone
        from app.repositories import EmployeeShiftRepository
        shifts_repo = EmployeeShiftRepository()
        
        shift = shifts_repo.get_shift_by_id(org_id, shift_id)
        if not shift:
            return {"success": False, "error": "Shift not found"}
        
        employee_id = shift.get("employee_id")
        if not employee_id:
            return {"success": False, "error": "Employee not assigned"}
        
        employee = employees_repo.get_employee_by_id(org_id, employee_id)
        if not employee:
            return {"success": False, "error": "Employee not found"}
        
        emp_phone = employee.get("phone")
        if not emp_phone or not emp_phone.strip():
            return {"success": False, "error": "Employee phone missing"}
        
        return {
            "success": True,
            "phone": emp_phone,
            "name": employee.get("name", ""),
        }
    
    return {"success": False, "error": f"Unknown message type: {message_type}"}
