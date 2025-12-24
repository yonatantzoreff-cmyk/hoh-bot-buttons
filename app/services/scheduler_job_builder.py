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


def _generate_job_id(org_id: int, entity_type: str, entity_id: int, message_type: str) -> str:
    """
    Generate a deterministic job_id for scheduled messages.
    
    Format: org_{org_id}_{entity_type}_{entity_id}_{message_type}_{uuid}
    
    Args:
        org_id: Organization ID
        entity_type: "event" or "shift"
        entity_id: Event ID or Shift ID
        message_type: "INIT", "TECH_REMINDER", or "SHIFT_REMINDER"
    
    Returns:
        A unique job_id string
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
        # Basic validation - should have at least 10 digits
        if len(normalized.replace("+", "").replace("-", "")) >= 10:
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
        Dictionary with keys: init_job_id, tech_job_id, init_status, tech_status
    """
    events_repo = EventRepository()
    scheduled_repo = ScheduledMessageRepository()
    settings_repo = SchedulerSettingsRepository()
    contacts_repo = ContactRepository()
    
    # Get event details
    event = events_repo.get_event_by_id(org_id=org_id, event_id=event_id)
    if not event:
        logger.error(f"Event {event_id} not found for org {org_id}")
        return {"error": "Event not found"}
    
    event_date = event.get("event_date")
    if not event_date:
        logger.warning(f"Event {event_id} has no event_date, cannot schedule jobs")
        return {"error": "Event date missing"}
    
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
        if isinstance(init_send_time, datetime):
            init_send_time = init_send_time.strftime("%H:%M")
        
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
                # Update send_at
                scheduled_repo.update_send_at(init_job["job_id"], init_send_at)
                
                # Update status based on phone validation
                if not phone_valid:
                    scheduled_repo.update_status(
                        init_job["job_id"],
                        status="blocked",
                        last_error="Producer phone number missing or invalid"
                    )
                    result["init_status"] = "blocked"
                else:
                    # If previously blocked and now phone is valid, unblock
                    if existing_status == "blocked":
                        scheduled_repo.update_status(
                            init_job["job_id"],
                            status="scheduled",
                            last_error=None
                        )
                    result["init_status"] = "updated"
                
                result["init_job_id"] = init_job["job_id"]
                logger.info(f"Updated INIT job {init_job['job_id']} for event {event_id}")
            else:
                result["init_job_id"] = init_job["job_id"]
                result["init_status"] = "already_sent_or_failed"
        else:
            # Create new job
            job_id = _generate_job_id(org_id, "event", event_id, "INIT")
            
            # Set status based on phone validation
            if not phone_valid:
                status = "blocked"
                last_error = "Producer phone number missing or invalid"
            else:
                status = "scheduled"
                last_error = None
            
            scheduled_repo.create_scheduled_message(
                job_id=job_id,
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
            logger.info(f"Created INIT job {job_id} for event {event_id}, status={status}")
    else:
        result["init_status"] = "disabled"
    
    # --- TECH_REMINDER Job ---
    if settings.get("enabled_global") and settings.get("enabled_tech"):
        tech_job = scheduled_repo.find_job_for_event(org_id, event_id, "TECH_REMINDER")
        
        # Compute send_at for TECH_REMINDER
        tech_days_before = settings.get("tech_days_before", 2)
        tech_send_time = settings.get("tech_send_time") or "12:00"
        if isinstance(tech_send_time, datetime):
            tech_send_time = tech_send_time.strftime("%H:%M")
        
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
                # Update send_at
                scheduled_repo.update_send_at(tech_job["job_id"], tech_send_at)
                
                # Update status based on phone validation
                if not phone_valid:
                    scheduled_repo.update_status(
                        tech_job["job_id"],
                        status="blocked",
                        last_error="Technical contact phone number missing or invalid"
                    )
                    result["tech_status"] = "blocked"
                else:
                    # If previously blocked and now phone is valid, unblock
                    if existing_status == "blocked":
                        scheduled_repo.update_status(
                            tech_job["job_id"],
                            status="scheduled",
                            last_error=None
                        )
                    result["tech_status"] = "updated"
                
                result["tech_job_id"] = tech_job["job_id"]
                logger.info(f"Updated TECH_REMINDER job {tech_job['job_id']} for event {event_id}")
            else:
                result["tech_job_id"] = tech_job["job_id"]
                result["tech_status"] = "already_sent_or_failed"
        else:
            # Create new job
            job_id = _generate_job_id(org_id, "event", event_id, "TECH_REMINDER")
            
            # Set status based on phone validation
            if not phone_valid:
                status = "blocked"
                last_error = "Technical contact phone number missing or invalid"
            else:
                status = "scheduled"
                last_error = None
            
            scheduled_repo.create_scheduled_message(
                job_id=job_id,
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
            logger.info(f"Created TECH_REMINDER job {job_id} for event {event_id}, status={status}")
    else:
        result["tech_status"] = "disabled"
    
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
        Dictionary with keys: processed_count, created, updated, blocked, disabled
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
        return {"processed_count": 0, "disabled": True}
    
    # Get all shifts for this event
    shifts = shifts_repo.list_shifts_for_event(org_id=org_id, event_id=event_id)
    
    now = now_utc()
    created = 0
    updated = 0
    blocked = 0
    
    shift_days_before = settings.get("shift_days_before", 1)
    shift_send_time = settings.get("shift_send_time") or "12:00"
    if isinstance(shift_send_time, datetime):
        shift_send_time = shift_send_time.strftime("%H:%M")
    
    for shift in shifts:
        shift_id = shift.get("shift_id")
        employee_id = shift.get("employee_id")
        call_time = shift.get("call_time")
        
        if not call_time:
            logger.warning(f"Shift {shift_id} has no call_time, skipping")
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
                # Update send_at
                scheduled_repo.update_send_at(existing_job["job_id"], send_at)
                
                # Update status based on phone validation
                if not phone_valid:
                    scheduled_repo.update_status(
                        existing_job["job_id"],
                        status="blocked",
                        last_error="Employee phone number missing or invalid"
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
                
                logger.info(f"Updated SHIFT_REMINDER job {existing_job['job_id']} for shift {shift_id}")
        else:
            # Create new job
            job_id = _generate_job_id(org_id, "shift", shift_id, "SHIFT_REMINDER")
            
            # Set status based on phone validation
            if not phone_valid:
                status = "blocked"
                last_error = "Employee phone number missing or invalid"
            else:
                status = "scheduled"
                last_error = None
            
            scheduled_repo.create_scheduled_message(
                job_id=job_id,
                org_id=org_id,
                message_type="SHIFT_REMINDER",
                send_at=send_at,
                shift_id=shift_id,
                is_enabled=True
            )
            
            # Update status if blocked
            if status == "blocked":
                scheduled_repo.update_status(job_id, status=status, last_error=last_error)
                blocked += 1
            else:
                created += 1
            
            logger.info(f"Created SHIFT_REMINDER job {job_id} for shift {shift_id}, status={status}")
    
    return {
        "processed_count": len(shifts),
        "created": created,
        "updated": updated,
        "blocked": blocked,
        "disabled": False
    }
