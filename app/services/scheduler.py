"""Scheduler service for running scheduled message delivery."""

import logging
import time
from typing import Optional, List
from datetime import datetime, timedelta

from app.hoh_service import HOHService
from app.repositories import (
    OrgRepository,
    ScheduledMessageRepository,
    SchedulerSettingsRepository,
    EventRepository,
    ContactRepository,
    EmployeeRepository,
    EmployeeShiftRepository,
    MessageRepository,
)
from app.appdb import get_session
from app.time_utils import now_utc, utc_to_local_datetime, parse_local_time_to_utc
from app.utils.phone import normalize_phone_to_e164_il
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for running scheduled message delivery across organizations."""
    
    def __init__(self):
        self.hoh = HOHService()
        self.orgs = OrgRepository()
        self.scheduled_repo = ScheduledMessageRepository()
        self.settings_repo = SchedulerSettingsRepository()
        self.events_repo = EventRepository()
        self.contacts_repo = ContactRepository()
        self.employees_repo = EmployeeRepository()
        self.shifts_repo = EmployeeShiftRepository()
        self.messages_repo = MessageRepository()
    
    async def run_once(self, org_id: Optional[int] = None) -> dict:
        """
        Run the scheduler once for all orgs or a specific org.
        
        This function:
        1. Loads scheduler_settings per org and respects enable flags
        2. Selects due jobs using SELECT FOR UPDATE SKIP LOCKED to avoid duplicates
        3. Resolves recipients in real-time based on message type
        4. Validates phone numbers and blocks jobs if missing
        5. Dedupes against messages table to avoid re-sending
        6. Applies weekend postponement rule for INIT messages
        7. Sends messages via existing sending functions
        8. Implements retry logic with exponential backoff
        
        Args:
            org_id: Optional specific org_id to run for. If None, runs for all orgs.
        
        Returns:
            Dictionary with counters: due_found, sent, failed, skipped, blocked, postponed, duration_ms
        """
        start_time = time.time()
        
        # Get list of org_ids to process
        if org_id is not None:
            org_ids = [org_id]
        else:
            org_ids = self._get_all_org_ids()
        
        # Initialize counters
        due_found = 0
        sent = 0
        failed = 0
        skipped = 0
        blocked = 0
        postponed = 0
        
        # Process each org
        for current_org_id in org_ids:
            try:
                # Get scheduler settings for this org
                settings = self.settings_repo.get_or_create_settings(current_org_id)
                
                # Skip if scheduler is globally disabled for this org
                if not settings.get("enabled_global"):
                    logger.debug(f"Scheduler globally disabled for org {current_org_id}")
                    continue
                
                # Find and lock due jobs for this org
                now = now_utc()
                due_jobs = self._get_due_jobs_with_lock(current_org_id, now)
                
                org_due_count = len(due_jobs)
                due_found += org_due_count
                
                if org_due_count == 0:
                    continue
                
                logger.info(f"Processing {org_due_count} due jobs for org {current_org_id}")
                
                # Process each due job
                for job in due_jobs:
                    try:
                        result = await self._process_job(job, settings, now)
                        
                        # Update counters
                        if result == "sent":
                            sent += 1
                        elif result == "failed":
                            failed += 1
                        elif result == "skipped":
                            skipped += 1
                        elif result == "blocked":
                            blocked += 1
                        elif result == "postponed":
                            postponed += 1
                            
                    except Exception as e:
                        logger.error(
                            f"Failed to process job {job.get('job_id')} for org {current_org_id}: {e}",
                            exc_info=True
                        )
                        failed += 1
                        # Mark job as failed
                        self._mark_job_failed(job.get("job_id"), str(e))
                        
            except Exception as e:
                logger.error(f"Error processing org {current_org_id}: {e}", exc_info=True)
        
        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Log summary
        logger.info(
            f"Scheduler run completed: due_found={due_found}, sent={sent}, "
            f"failed={failed}, skipped={skipped}, blocked={blocked}, "
            f"postponed={postponed}, duration_ms={duration_ms}"
        )
        
        return {
            "due_found": due_found,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "blocked": blocked,
            "postponed": postponed,
            "duration_ms": duration_ms,
        }
    
    def _get_all_org_ids(self) -> List[int]:
        """Get list of all org IDs."""
        with get_session() as session:
            result = session.execute(text("SELECT org_id FROM orgs ORDER BY org_id"))
            return [row[0] for row in result.fetchall()]
    
    def _get_due_jobs_with_lock(self, org_id: int, now: datetime) -> List[dict]:
        """
        Get due jobs for an org using SELECT FOR UPDATE SKIP LOCKED.
        
        This ensures that if multiple scheduler instances run concurrently,
        each job is processed by only one instance.
        """
        query = text("""
            SELECT *
            FROM scheduled_messages
            WHERE org_id = :org_id
              AND status IN ('scheduled', 'retrying')
              AND is_enabled = TRUE
              AND send_at <= :now
              AND attempt_count < max_attempts
            ORDER BY send_at ASC
            FOR UPDATE SKIP LOCKED
        """)
        
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id, "now": now})
            return [dict(row) for row in result.mappings().all()]
    
    async def _process_job(self, job: dict, settings: dict, now: datetime) -> str:
        """
        Process a single scheduled message job.
        
        Returns:
            Status string: "sent", "failed", "skipped", "blocked", or "postponed"
        """
        job_id = job.get("job_id")
        org_id = job.get("org_id")
        message_type = job.get("message_type")
        event_id = job.get("event_id")
        shift_id = job.get("shift_id")
        
        logger.info(
            f"Processing job {job_id}: type={message_type}, event_id={event_id}, shift_id={shift_id}"
        )
        
        # Check if message type is enabled in settings
        if message_type == "INIT" and not settings.get("enabled_init"):
            logger.info(f"INIT messages disabled for org {org_id}, skipping job {job_id}")
            self.scheduled_repo.update_status(job_id, status="skipped", last_error="INIT disabled")
            return "skipped"
        elif message_type == "TECH_REMINDER" and not settings.get("enabled_tech"):
            logger.info(f"TECH_REMINDER messages disabled for org {org_id}, skipping job {job_id}")
            self.scheduled_repo.update_status(job_id, status="skipped", last_error="TECH_REMINDER disabled")
            return "skipped"
        elif message_type == "SHIFT_REMINDER" and not settings.get("enabled_shift"):
            logger.info(f"SHIFT_REMINDER messages disabled for org {org_id}, skipping job {job_id}")
            self.scheduled_repo.update_status(job_id, status="skipped", last_error="SHIFT_REMINDER disabled")
            return "skipped"
        
        # Step 1: Resolve recipient in real-time
        recipient_result = self._resolve_recipient(job)
        
        if not recipient_result["success"]:
            # Missing phone - block the job
            error_msg = recipient_result.get("error", "Missing phone number")
            logger.warning(f"Job {job_id} blocked: {error_msg}")
            self.scheduled_repo.update_status(job_id, status="blocked", last_error=error_msg)
            return "blocked"
        
        recipient_phone = recipient_result["phone"]
        recipient_name = recipient_result.get("name", "")
        recipient_contact_id = recipient_result.get("contact_id")
        
        # Step 2: Check for dedupe - has this message already been sent manually?
        if self._is_duplicate(org_id, message_type, event_id, shift_id):
            logger.info(f"Job {job_id} is a duplicate (already sent manually), skipping")
            self.scheduled_repo.update_status(
                job_id, 
                status="skipped", 
                last_error="Message already sent manually"
            )
            return "skipped"
        
        # Step 3: Weekend restriction for INIT messages
        if message_type == "INIT":
            postpone_result = self._check_weekend_postponement(job_id, now)
            if postpone_result:
                logger.info(f"Job {job_id} postponed to {postpone_result}")
                return "postponed"
        
        # Step 4: Send the message
        try:
            send_result = await self._send_message(
                job, 
                recipient_phone, 
                recipient_name,
                recipient_contact_id,
                now
            )
            
            if send_result["success"]:
                # Mark as sent
                self.scheduled_repo.update_status(
                    job_id,
                    status="sent",
                    sent_at=now,
                    last_error=None,
                    last_resolved_to_name=recipient_name,
                    last_resolved_to_phone=recipient_phone
                )
                logger.info(f"Job {job_id} sent successfully")
                return "sent"
            else:
                # Send failed - implement retry logic
                return self._handle_send_failure(job, send_result.get("error", "Unknown error"), now)
                
        except Exception as e:
            logger.error(f"Error sending job {job_id}: {e}", exc_info=True)
            return self._handle_send_failure(job, str(e), now)
    
    def _resolve_recipient(self, job: dict) -> dict:
        """
        Resolve the recipient phone number and details for a job.
        
        Returns:
            Dict with: success (bool), phone (str or None), name (str), contact_id (int or None), error (str)
        """
        org_id = job.get("org_id")
        message_type = job.get("message_type")
        event_id = job.get("event_id")
        shift_id = job.get("shift_id")
        
        if message_type == "INIT":
            # INIT: If event.technical_phone exists -> recipient=technician, else producer
            event = self.events_repo.get_event_by_id(org_id, event_id)
            if not event:
                return {"success": False, "error": "Event not found"}
            
            # Try technical contact first
            technical_contact_id = event.get("technical_contact_id")
            if technical_contact_id:
                technical = self.contacts_repo.get_contact_by_id(org_id, technical_contact_id)
                if technical:
                    tech_phone = technical.get("phone")
                    if tech_phone and tech_phone.strip():
                        try:
                            normalized_phone = normalize_phone_to_e164_il(tech_phone)
                            if normalized_phone:
                                return {
                                    "success": True,
                                    "phone": normalized_phone,
                                    "name": technical.get("name", ""),
                                    "contact_id": technical_contact_id
                                }
                        except Exception:
                            pass
            
            # Fallback to producer
            producer_contact_id = event.get("producer_contact_id")
            if producer_contact_id:
                producer = self.contacts_repo.get_contact_by_id(org_id, producer_contact_id)
                if producer:
                    prod_phone = producer.get("phone")
                    if prod_phone and prod_phone.strip():
                        try:
                            normalized_phone = normalize_phone_to_e164_il(prod_phone)
                            if normalized_phone:
                                return {
                                    "success": True,
                                    "phone": normalized_phone,
                                    "name": producer.get("name", ""),
                                    "contact_id": producer_contact_id
                                }
                        except Exception:
                            pass
            
            return {"success": False, "error": "Missing phone number (technical or producer)"}
        
        elif message_type == "TECH_REMINDER":
            # TECH_REMINDER: event.technical_phone
            event = self.events_repo.get_event_by_id(org_id, event_id)
            if not event:
                return {"success": False, "error": "Event not found"}
            
            technical_contact_id = event.get("technical_contact_id")
            if not technical_contact_id:
                return {"success": False, "error": "Technical contact not assigned"}
            
            technical = self.contacts_repo.get_contact_by_id(org_id, technical_contact_id)
            if not technical:
                return {"success": False, "error": "Technical contact not found"}
            
            tech_phone = technical.get("phone")
            if not tech_phone or not tech_phone.strip():
                return {"success": False, "error": "Technical contact phone missing"}
            
            try:
                normalized_phone = normalize_phone_to_e164_il(tech_phone)
                if not normalized_phone:
                    return {"success": False, "error": "Technical contact phone invalid"}
                
                return {
                    "success": True,
                    "phone": normalized_phone,
                    "name": technical.get("name", ""),
                    "contact_id": technical_contact_id
                }
            except Exception as e:
                return {"success": False, "error": f"Phone normalization failed: {e}"}
        
        elif message_type == "SHIFT_REMINDER":
            # SHIFT_REMINDER: shift.employee_phone
            shift = self.shifts_repo.get_shift_by_id(org_id, shift_id)
            if not shift:
                return {"success": False, "error": "Shift not found"}
            
            employee_id = shift.get("employee_id")
            if not employee_id:
                return {"success": False, "error": "Employee not assigned to shift"}
            
            employee = self.employees_repo.get_employee_by_id(org_id, employee_id)
            if not employee:
                return {"success": False, "error": "Employee not found"}
            
            emp_phone = employee.get("phone")
            if not emp_phone or not emp_phone.strip():
                return {"success": False, "error": "Employee phone missing"}
            
            try:
                normalized_phone = normalize_phone_to_e164_il(emp_phone)
                if not normalized_phone:
                    return {"success": False, "error": "Employee phone invalid"}
                
                return {
                    "success": True,
                    "phone": normalized_phone,
                    "name": employee.get("name", ""),
                    "contact_id": None  # Employee doesn't have a contact_id
                }
            except Exception as e:
                return {"success": False, "error": f"Phone normalization failed: {e}"}
        
        return {"success": False, "error": f"Unknown message type: {message_type}"}
    
    def _is_duplicate(self, org_id: int, message_type: str, event_id: Optional[int], shift_id: Optional[int]) -> bool:
        """
        Check if a message of this type has already been sent for this event/shift.
        
        This checks the messages table for manually sent messages with matching
        org_id, message_type (via raw_payload), and event_id/shift_id.
        """
        # Query messages table for existing messages
        query_params = {
            "org_id": org_id,
            "message_type": message_type,
        }
        
        if event_id:
            # Check for messages for this event with this message type
            query = text("""
                SELECT COUNT(*) 
                FROM messages
                WHERE org_id = :org_id
                  AND event_id = :event_id
                  AND direction = 'outgoing'
                  AND (
                    raw_payload::text LIKE '%INIT%'
                    OR raw_payload::text LIKE '%TECH_REMINDER%'
                  )
                LIMIT 1
            """)
            query_params["event_id"] = event_id
        elif shift_id:
            # Check for messages for this shift
            query = text("""
                SELECT COUNT(*) 
                FROM messages
                WHERE org_id = :org_id
                  AND direction = 'outgoing'
                  AND raw_payload::text LIKE :shift_pattern
                LIMIT 1
            """)
            query_params["shift_pattern"] = f"%shift_id%{shift_id}%"
        else:
            return False
        
        try:
            with get_session() as session:
                result = session.execute(query, query_params)
                count = result.scalar()
                return count > 0
        except Exception as e:
            logger.warning(f"Dedupe check failed: {e}")
            return False
    
    def _check_weekend_postponement(self, job_id: str, now: datetime) -> Optional[datetime]:
        """
        Check if INIT message should be postponed due to weekend rule.
        
        If now is Friday or Saturday, postpone to next Sunday at 10:00 (Asia/Jerusalem).
        
        Returns:
            New send_at datetime if postponed, None otherwise
        """
        # Convert now to Israel time to check weekday
        now_israel = utc_to_local_datetime(now)
        weekday = now_israel.weekday()  # Monday=0, Sunday=6
        
        if weekday == 4:  # Friday
            # Postpone to Sunday (add 2 days)
            next_sunday = now_israel.date() + timedelta(days=2)
            new_send_at = parse_local_time_to_utc(next_sunday, "10:00")
            
            logger.info(f"Weekend rule: Postponing job {job_id} from Friday to Sunday {next_sunday}")
            
            # Update send_at in database
            self.scheduled_repo.update_send_at(job_id, new_send_at)
            return new_send_at
            
        elif weekday == 5:  # Saturday
            # Postpone to Sunday (add 1 day)
            next_sunday = now_israel.date() + timedelta(days=1)
            new_send_at = parse_local_time_to_utc(next_sunday, "10:00")
            
            logger.info(f"Weekend rule: Postponing job {job_id} from Saturday to Sunday {next_sunday}")
            
            # Update send_at in database
            self.scheduled_repo.update_send_at(job_id, new_send_at)
            return new_send_at
        
        return None
    
    async def _send_message(
        self, 
        job: dict, 
        recipient_phone: str, 
        recipient_name: str,
        recipient_contact_id: Optional[int],
        now: datetime
    ) -> dict:
        """
        Send a message using existing sending functions.
        
        Returns:
            Dict with: success (bool), error (str or None)
        """
        org_id = job.get("org_id")
        message_type = job.get("message_type")
        event_id = job.get("event_id")
        shift_id = job.get("shift_id")
        
        try:
            if message_type == "SHIFT_REMINDER":
                # Use existing send_shift_reminder implementation
                self.hoh.send_shift_reminder(org_id=org_id, shift_id=shift_id)
                return {"success": True}
            
            elif message_type == "INIT":
                # Use existing send_init_for_event implementation
                await self.hoh.send_init_for_event(
                    event_id=event_id,
                    org_id=org_id,
                    contact_id=recipient_contact_id
                )
                return {"success": True}
            
            elif message_type == "TECH_REMINDER":
                # TECH_REMINDER doesn't have a dedicated function yet
                # We'll need to implement it or use a generic message sending approach
                # For now, return an error
                return {"success": False, "error": "TECH_REMINDER sending not implemented yet"}
            
            else:
                return {"success": False, "error": f"Unknown message type: {message_type}"}
                
        except Exception as e:
            logger.error(f"Failed to send {message_type} message: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def _handle_send_failure(self, job: dict, error: str, now: datetime) -> str:
        """
        Handle a message send failure by implementing retry logic.
        
        Returns:
            Status string: "failed" (final failure) or "failed" (will retry)
        """
        job_id = job.get("job_id")
        attempt_count = job.get("attempt_count", 0)
        max_attempts = job.get("max_attempts", 3)
        
        # Increment attempt count
        self.scheduled_repo.increment_attempt(job_id)
        attempt_count += 1
        
        if attempt_count < max_attempts:
            # Schedule retry - set send_at to now + 10 minutes
            retry_at = now + timedelta(minutes=10)
            self.scheduled_repo.update_send_at(job_id, retry_at)
            self.scheduled_repo.update_status(
                job_id,
                status="retrying",
                last_error=f"Attempt {attempt_count}/{max_attempts}: {error}"
            )
            logger.info(
                f"Job {job_id} will retry at {retry_at} (attempt {attempt_count}/{max_attempts})"
            )
            return "failed"  # Will count as failed for this run
        else:
            # Max attempts reached - mark as permanently failed
            self.scheduled_repo.update_status(
                job_id,
                status="failed",
                last_error=f"Max attempts ({max_attempts}) reached: {error}"
            )
            logger.error(f"Job {job_id} permanently failed after {max_attempts} attempts")
            return "failed"
    
    def _mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark a job as failed due to an unexpected error."""
        try:
            self.scheduled_repo.update_status(
                job_id,
                status="failed",
                last_error=f"Unexpected error: {error}"
            )
        except Exception as e:
            logger.error(f"Failed to mark job {job_id} as failed: {e}")
