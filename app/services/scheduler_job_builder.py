"""
Scheduler Job Builder Service

This module provides functions to build or update scheduled message jobs for events and shifts.
It ensures exactly one job exists per event/message-type or per shift/message-type, and handles
the computation of send_at timestamps using configurable rules.

Key functions:
- build_or_update_jobs_for_event: Create/update INIT and TECH_REMINDER jobs for an event
- build_or_update_jobs_for_shifts: Create/update SHIFT_REMINDER jobs for all shifts in an event
"""

import logging
from datetime import datetime
from typing import Optional
import uuid

from app.repositories import (
    EventRepository,
    ScheduledMessageRepository,
    SchedulerSettingsRepository,
    EmployeeRepository,
    EmployeeShiftRepository,
    ContactRepository,
)
from app.time_utils import compute_send_at, now_utc, utc_to_local_datetime
from app.utils.phone import normalize_phone_to_e164_il

logger = logging.getLogger(__name__)

# Phone validation constants
MIN_PHONE_DIGITS = 10  # Minimum number of digits required for a valid phone number

# Error message constants
ERROR_MSG_MISSING_RECIPIENT_PHONE = "Missing recipient phone"

# Skip reason constants
SKIP_REASON_MISSING_EVENT_ID = "missing_event_id"
SKIP_REASON_MISSING_EVENT_DATE = "missing_event_date"
SKIP_REASON_MISSING_REQUIRED_TIME_FIELDS = "missing_required_time_fields"
SKIP_REASON_ALREADY_UP_TO_DATE = "already_up_to_date"
SKIP_REASON_ALREADY_SENT_OR_FAILED = "already_sent_or_failed"
SKIP_REASON_DISABLED_BY_SETTINGS = "disabled_by_settings"


def _has_send_at_changed(existing_send_at, new_send_at) -> bool:
    """
    Check if send_at timestamp has changed.
    
    Args:
        existing_send_at: Existing send_at timestamp
        new_send_at: New send_at timestamp
    
    Returns:
        True if send_at has changed, False otherwise
    """
    return existing_send_at != new_send_at


def _generate_job_key(org_id: int, entity_type: str, entity_id: int, message_type: str) -> str:
    """
    Generate a deterministic job_key for scheduled messages.
    
    Format: org_{org_id}_{entity_type}_{entity_id}_{message_type}_{uuid}
    
    Args:
        org_id: Organization ID
        entity_type: "event" or "shift"
        entity_id: Event ID or Shift ID
        message_type: "INIT", "TECH_REMINDER", or "SHIFT_REMINDER"
    
    Returns:
        A unique job_key string used for idempotency
    """
    unique_suffix = str(uuid.uuid4())[:8]
    return f"org_{org_id}_{entity_type}_{entity_id}_{message_type}_{unique_suffix}"


def _validate_phone(phone: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Validate and normalize a phone number.
    
    Args:
        phone: Phone number to validate (can be None)
    
    Returns:
        Tuple of (is_valid, normalized_phone_or_none)
    """
    if not phone:
        return False, None
    
    try:
        normalized = normalize_phone_to_e164_il(phone)
        # Basic validation - should have at least MIN_PHONE_DIGITS digits
        if len(normalized.replace("+", "").replace("-", "")) >= MIN_PHONE_DIGITS:
            return True, normalized
        return False, None
    except Exception as e:
        logger.warning(f"Phone validation failed for {phone}: {e}")
        return False, None


def build_or_update_jobs_for_event(org_id: int, event_id: int) -> dict:
    """
    Build or update scheduled message jobs for an event.
    
    Creates exactly one INIT job and one TECH_REMINDER job per event.
    - INIT: Scheduled at event_date - 28 days (default) at 10:00 (default), with weekend rule
    - TECH_REMINDER: Scheduled at event_date - 2 days (default) at 12:00 (default), no weekend rule
    
    If a job already exists and is not sent/failed, updates the send_at timestamp.
    If required phone is missing, sets status=blocked with error message.
    
    Args:
        org_id: Organization ID
        event_id: Event ID
    
    Returns:
        Dictionary with keys: 
        - init_job_id, tech_job_id, init_status, tech_status
        - init_skip_reason, tech_skip_reason (optional, if skipped)
    """
    events_repo = EventRepository()
    scheduled_repo = ScheduledMessageRepository()
    settings_repo = SchedulerSettingsRepository()
    contacts_repo = ContactRepository()
    
    # Get event details
    event = events_repo.get_event_by_id(org_id=org_id, event_id=event_id)
    if not event:
        logger.error(f"Event {event_id} not found for org {org_id}")
        return {
            "error": "Event not found",
            "init_status": "skipped",
            "init_skip_reason": SKIP_REASON_MISSING_EVENT_ID,
            "tech_status": "skipped",
            "tech_skip_reason": SKIP_REASON_MISSING_EVENT_ID
        }
    
    event_date = event.get("event_date")
    if not event_date:
        logger.warning(f"Event {event_id} has no event_date, cannot schedule jobs")
        return {
            "error": "Event date missing",
            "init_status": "skipped",
            "init_skip_reason": SKIP_REASON_MISSING_EVENT_DATE,
            "tech_status": "skipped",
            "tech_skip_reason": SKIP_REASON_MISSING_EVENT_DATE
        }
    
    # Get scheduler settings (with defaults)
    settings = settings_repo.get_or_create_settings(org_id)
    
    # Get producer phone for INIT message
    producer_contact_id = event.get("producer_contact_id")
    producer_phone = None
    if producer_contact_id:
        producer = contacts_repo.get_contact_by_id(org_id=org_id, contact_id=producer_contact_id)
        if producer:
            producer_phone = producer.get("phone")
    
    # Get technical phone for TECH_REMINDER message
    technical_contact_id = event.get("technical_contact_id")
    technical_phone = None
    if technical_contact_id:
        technical = contacts_repo.get_contact_by_id(org_id=org_id, contact_id=technical_contact_id)
        if technical:
            technical_phone = technical.get("phone")
    
    now = now_utc()
    result = {}
    
    # --- INIT Job ---
    if settings.get("enabled_global") and settings.get("enabled_init"):
        init_job = scheduled_repo.find_job_for_event(org_id, event_id, "INIT")
        
        # Compute send_at for INIT
        init_days_before = settings.get("init_days_before", 28)
        init_send_time = settings.get("init_send_time") or "10:00"
        # parse_time helper now handles datetime.time, datetime, and string formats
        
        init_send_at = compute_send_at(
            base_date=event_date,
            fixed_time=init_send_time,
            days_before=init_days_before,
            now=now,
            apply_weekend_rule=True  # INIT uses weekend rule
        )
        
        # Validate producer phone
        phone_valid, _ = _validate_phone(producer_phone)
        
        if init_job:
            # Update existing job if not sent or failed
            existing_status = init_job.get("status")
            if existing_status not in ("sent", "failed"):
                # Check if send_at changed
                existing_send_at = init_job.get("send_at")
                send_at_changed = _has_send_at_changed(existing_send_at, init_send_at)
                
                if send_at_changed:
                    # Update send_at
                    scheduled_repo.update_send_at(init_job["job_id"], init_send_at)
                
                # Update status based on phone validation
                if not phone_valid:
                    scheduled_repo.update_status(
                        init_job["job_id"],
                        status="blocked",
                        last_error=ERROR_MSG_MISSING_RECIPIENT_PHONE
                    )
                    result["init_status"] = "blocked"
                elif existing_status == "blocked":
                    # Previously blocked and now phone is valid, unblock
                    scheduled_repo.update_status(
                        init_job["job_id"],
                        status="scheduled",
                        last_error=None
                    )
                    result["init_status"] = "updated"
                elif send_at_changed:
                    # Send time changed
                    result["init_status"] = "updated"
                else:
                    # No changes - already up to date
                    result["init_status"] = "skipped"
                    result["init_skip_reason"] = SKIP_REASON_ALREADY_UP_TO_DATE
                
                result["init_job_id"] = init_job["job_id"]
                if result.get("init_status") == "updated":
                    logger.info(f"Updated INIT job {init_job['job_id']} for event {event_id}")
            else:
                result["init_job_id"] = init_job["job_id"]
                result["init_status"] = "skipped"
                result["init_skip_reason"] = SKIP_REASON_ALREADY_SENT_OR_FAILED
        else:
            # Create new job - ALWAYS create even if phone is missing (status=blocked)
            job_key = _generate_job_key(org_id, "event", event_id, "INIT")
            
            # Set status based on phone validation
            if not phone_valid:
                status = "blocked"
                last_error = ERROR_MSG_MISSING_RECIPIENT_PHONE
            else:
                status = "scheduled"
                last_error = None
            
            job_id = scheduled_repo.create_scheduled_message(
                job_key=job_key,
                org_id=org_id,
                message_type="INIT",
                send_at=init_send_at,
                event_id=event_id,
                is_enabled=True
            )
            
            # Update status if blocked
            if status == "blocked":
                scheduled_repo.update_status(job_id, status=status, last_error=last_error)
            
            result["init_job_id"] = job_id
            result["init_status"] = "blocked" if status == "blocked" else "created"
            logger.info(f"Created INIT job {job_id} (key={job_key}) for event {event_id}, status={status}")
    else:
        result["init_status"] = "skipped"
        result["init_skip_reason"] = SKIP_REASON_DISABLED_BY_SETTINGS
    
    # --- TECH_REMINDER Job ---
    if settings.get("enabled_global") and settings.get("enabled_tech"):
        tech_job = scheduled_repo.find_job_for_event(org_id, event_id, "TECH_REMINDER")
        
        # Compute send_at for TECH_REMINDER
        tech_days_before = settings.get("tech_days_before", 2)
        tech_send_time = settings.get("tech_send_time") or "12:00"
        # parse_time helper now handles datetime.time, datetime, and string formats
        
        tech_send_at = compute_send_at(
            base_date=event_date,
            fixed_time=tech_send_time,
            days_before=tech_days_before,
            now=now,
            apply_weekend_rule=False  # TECH_REMINDER does NOT use weekend rule
        )
        
        # Validate technical phone
        phone_valid, _ = _validate_phone(technical_phone)
        
        if tech_job:
            # Update existing job if not sent or failed
            existing_status = tech_job.get("status")
            if existing_status not in ("sent", "failed"):
                # Check if send_at changed
                existing_send_at = tech_job.get("send_at")
                send_at_changed = _has_send_at_changed(existing_send_at, tech_send_at)
                
                if send_at_changed:
                    # Update send_at
                    scheduled_repo.update_send_at(tech_job["job_id"], tech_send_at)
                
                # Update status based on phone validation
                if not phone_valid:
                    scheduled_repo.update_status(
                        tech_job["job_id"],
                        status="blocked",
                        last_error=ERROR_MSG_MISSING_RECIPIENT_PHONE
                    )
                    result["tech_status"] = "blocked"
                elif existing_status == "blocked":
                    # Previously blocked and now phone is valid, unblock
                    scheduled_repo.update_status(
                        tech_job["job_id"],
                        status="scheduled",
                        last_error=None
                    )
                    result["tech_status"] = "updated"
                elif send_at_changed:
                    # Send time changed
                    result["tech_status"] = "updated"
                else:
                    # No changes - already up to date
                    result["tech_status"] = "skipped"
                    result["tech_skip_reason"] = SKIP_REASON_ALREADY_UP_TO_DATE
                
                result["tech_job_id"] = tech_job["job_id"]
                if result.get("tech_status") == "updated":
                    logger.info(f"Updated TECH_REMINDER job {tech_job['job_id']} for event {event_id}")
            else:
                result["tech_job_id"] = tech_job["job_id"]
                result["tech_status"] = "skipped"
                result["tech_skip_reason"] = SKIP_REASON_ALREADY_SENT_OR_FAILED
        else:
            # Create new job - ALWAYS create even if phone is missing (status=blocked)
            job_key = _generate_job_key(org_id, "event", event_id, "TECH_REMINDER")
            
            # Set status based on phone validation
            if not phone_valid:
                status = "blocked"
                last_error = ERROR_MSG_MISSING_RECIPIENT_PHONE
            else:
                status = "scheduled"
                last_error = None
            
            job_id = scheduled_repo.create_scheduled_message(
                job_key=job_key,
                org_id=org_id,
                message_type="TECH_REMINDER",
                send_at=tech_send_at,
                event_id=event_id,
                is_enabled=True
            )
            
            # Update status if blocked
            if status == "blocked":
                scheduled_repo.update_status(job_id, status=status, last_error=last_error)
            
            result["tech_job_id"] = job_id
            result["tech_status"] = "blocked" if status == "blocked" else "created"
            logger.info(f"Created TECH_REMINDER job {job_id} (key={job_key}) for event {event_id}, status={status}")
    else:
        result["tech_status"] = "skipped"
        result["tech_skip_reason"] = SKIP_REASON_DISABLED_BY_SETTINGS
    
    return result


def build_or_update_jobs_for_shifts(org_id: int, event_id: int) -> dict:
    """
    Build or update scheduled message jobs for all shifts in an event.
    
    For each shift row, ensures one SHIFT_REMINDER job exists.
    - SHIFT_REMINDER: Scheduled at shift_date - 1 day (default) at 12:00 (default), no weekend rule
    
    If a job already exists and is not sent/failed, updates the send_at timestamp.
    If employee phone is missing, sets status=blocked with error message.
    
    Args:
        org_id: Organization ID
        event_id: Event ID
    
    Returns:
        Dictionary with keys: 
        - processed_count, created, updated, blocked, disabled, skipped
        - skip_reasons (dict of reason -> count)
    """
    shifts_repo = EmployeeShiftRepository()
    scheduled_repo = ScheduledMessageRepository()
    settings_repo = SchedulerSettingsRepository()
    employees_repo = EmployeeRepository()
    
    # Get scheduler settings (with defaults)
    settings = settings_repo.get_or_create_settings(org_id)
    
    # Check if shift reminders are enabled
    if not settings.get("enabled_global") or not settings.get("enabled_shift"):
        logger.info(f"Shift reminders disabled for org {org_id}")
        return {
            "processed_count": 0, 
            "disabled": True,
            "skip_reasons": {SKIP_REASON_DISABLED_BY_SETTINGS: 0}
        }
    
    # Get all shifts for this event
    shifts = shifts_repo.list_shifts_for_event(org_id=org_id, event_id=event_id)
    
    now = now_utc()
    created = 0
    updated = 0
    blocked = 0
    skipped = 0
    skip_reasons = {}
    
    shift_days_before = settings.get("shift_days_before", 1)
    shift_send_time = settings.get("shift_send_time") or "12:00"
    # parse_time helper now handles datetime.time, datetime, and string formats
    
    for shift in shifts:
        shift_id = shift.get("shift_id")
        employee_id = shift.get("employee_id")
        call_time = shift.get("call_time")
        
        if not call_time:
            logger.warning(f"Shift {shift_id} has no call_time, skipping")
            skipped += 1
            skip_reasons[SKIP_REASON_MISSING_REQUIRED_TIME_FIELDS] = skip_reasons.get(SKIP_REASON_MISSING_REQUIRED_TIME_FIELDS, 0) + 1
            continue
        
        # Get shift date (convert call_time to local date)
        call_time_local = utc_to_local_datetime(call_time)
        shift_date = call_time_local.date()
        
        # Get employee phone if assigned
        employee_phone = None
        if employee_id:
            employee = employees_repo.get_employee_by_id(org_id=org_id, employee_id=employee_id)
            if employee:
                employee_phone = employee.get("phone")
        
        # Validate phone
        phone_valid, _ = _validate_phone(employee_phone)
        
        # Compute send_at for SHIFT_REMINDER
        send_at = compute_send_at(
            base_date=shift_date,
            fixed_time=shift_send_time,
            days_before=shift_days_before,
            now=now,
            apply_weekend_rule=False  # SHIFT_REMINDER does NOT use weekend rule
        )
        
        # Find existing job
        existing_job = scheduled_repo.find_job_for_shift(org_id, shift_id, "SHIFT_REMINDER")
        
        if existing_job:
            # Update existing job if not sent or failed
            existing_status = existing_job.get("status")
            if existing_status not in ("sent", "failed"):
                # Check if send_at changed
                existing_send_at = existing_job.get("send_at")
                send_at_changed = _has_send_at_changed(existing_send_at, send_at)
                
                if send_at_changed:
                    # Update send_at
                    scheduled_repo.update_send_at(existing_job["job_id"], send_at)
                
                # Update status based on phone validation
                job_was_updated = False
                if not phone_valid:
                    scheduled_repo.update_status(
                        existing_job["job_id"],
                        status="blocked",
                        last_error=ERROR_MSG_MISSING_RECIPIENT_PHONE
                    )
                    blocked += 1
                else:
                    # If previously blocked and now phone is valid, unblock
                    if existing_status == "blocked":
                        scheduled_repo.update_status(
                            existing_job["job_id"],
                            status="scheduled",
                            last_error=None
                        )
                        updated += 1
                        job_was_updated = True
                    elif send_at_changed:
                        updated += 1
                        job_was_updated = True
                    else:
                        # No changes - already up to date
                        skipped += 1
                        skip_reasons[SKIP_REASON_ALREADY_UP_TO_DATE] = skip_reasons.get(SKIP_REASON_ALREADY_UP_TO_DATE, 0) + 1
                
                if job_was_updated or not phone_valid:
                    logger.info(f"Updated SHIFT_REMINDER job {existing_job['job_id']} for shift {shift_id}")
            else:
                # Already sent or failed
                skipped += 1
                skip_reasons[SKIP_REASON_ALREADY_SENT_OR_FAILED] = skip_reasons.get(SKIP_REASON_ALREADY_SENT_OR_FAILED, 0) + 1
        else:
            # Create new job - ALWAYS create even if phone is missing (status=blocked)
            job_key = _generate_job_key(org_id, "shift", shift_id, "SHIFT_REMINDER")
            
            # Validate that we have event_id (should always be present from function argument)
            if event_id is None:
                logger.error(f"Cannot create SHIFT_REMINDER for shift {shift_id}: event_id is None")
                skipped += 1
                skip_reasons[SKIP_REASON_MISSING_EVENT_ID] = skip_reasons.get(SKIP_REASON_MISSING_EVENT_ID, 0) + 1
                continue
            
            # Set status based on phone validation
            if not phone_valid:
                status = "blocked"
                last_error = ERROR_MSG_MISSING_RECIPIENT_PHONE
            else:
                status = "scheduled"
                last_error = None
            
            job_id = scheduled_repo.create_scheduled_message(
                job_key=job_key,
                org_id=org_id,
                message_type="SHIFT_REMINDER",
                send_at=send_at,
                event_id=event_id,  # Always set event_id for SHIFT_REMINDER
                shift_id=shift_id,
                is_enabled=True
            )
            
            # Update status if blocked
            if status == "blocked":
                scheduled_repo.update_status(job_id, status=status, last_error=last_error)
                blocked += 1
            else:
                created += 1
            
            logger.info(f"Created SHIFT_REMINDER job {job_id} (key={job_key}) for shift {shift_id}, event {event_id}, status={status}")
    
    return {
        "processed_count": len(shifts),
        "created": created,
        "updated": updated,
        "blocked": blocked,
        "skipped": skipped,
        "skip_reasons": skip_reasons,
        "disabled": False
    }
