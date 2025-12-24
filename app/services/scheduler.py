"""
Scheduler service for running periodic tasks like sending shift reminders.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.appdb import get_session
from app.hoh_service import HOHService
from app.time_utils import now_utc
from sqlalchemy import text

logger = logging.getLogger(__name__)


def find_shifts_needing_reminders(org_id: Optional[int] = None, hours_before: int = 24) -> list[dict]:
    """
    Find shifts that need 24-hour (or custom) reminders sent.
    
    A shift needs a reminder if:
    1. call_time - hours_before hours <= now
    2. call_time > now (shift hasn't started yet)
    3. reminder_24h_sent_at IS NULL (reminder not sent yet)
    
    Args:
        org_id: Organization ID to filter by (None = all orgs)
        hours_before: Number of hours before call_time to send reminder
    
    Returns:
        List of shifts needing reminders with shift details
    """
    now = now_utc()
    reminder_window_start = now + timedelta(hours=hours_before)
    
    query = text("""
        SELECT 
            s.shift_id,
            s.org_id,
            s.event_id,
            s.employee_id,
            s.call_time,
            s.shift_role,
            e.name AS employee_name,
            e.phone AS employee_phone
        FROM employee_shifts s
        LEFT JOIN employees e 
            ON e.employee_id = s.employee_id 
            AND e.org_id = s.org_id
        WHERE s.reminder_24h_sent_at IS NULL
          AND s.call_time > :now
          AND s.call_time <= :reminder_window_start
          AND (:org_id IS NULL OR s.org_id = :org_id)
        ORDER BY s.call_time ASC
    """)
    
    with get_session() as session:
        result = session.execute(
            query,
            {
                "now": now,
                "reminder_window_start": reminder_window_start,
                "org_id": org_id,
            }
        )
        return [dict(row._mapping) for row in result]


def run_once(org_id: Optional[int] = None) -> dict:
    """
    Run the scheduler once to process due reminders.
    
    Args:
        org_id: Optional organization ID to limit processing to a single org.
                If None, processes all organizations.
    
    Returns:
        Dictionary with counters:
        - due_found: Number of shifts needing reminders
        - sent: Number of reminders successfully sent
        - failed: Number of reminders that failed to send
        - skipped: Number of shifts skipped (e.g., invalid phone)
        - blocked: Number blocked by external factors
        - postponed: Number postponed for later
        - duration_ms: Time taken to run in milliseconds
    """
    start_time = datetime.now()
    
    counters = {
        "due_found": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "blocked": 0,
        "postponed": 0,
        "duration_ms": 0,
    }
    
    try:
        # Find shifts needing reminders
        shifts = find_shifts_needing_reminders(org_id=org_id)
        counters["due_found"] = len(shifts)
        
        if not shifts:
            logger.info("Scheduler run: no shifts due for reminders")
            return counters
        
        # Process each shift
        hoh = HOHService()
        for shift in shifts:
            shift_id = shift["shift_id"]
            shift_org_id = shift["org_id"]
            
            try:
                # Validate that shift has required data
                if not shift.get("employee_phone"):
                    logger.warning(f"Shift {shift_id}: skipping - no employee phone")
                    counters["skipped"] += 1
                    continue
                
                # Send the reminder
                hoh.send_shift_reminder(org_id=shift_org_id, shift_id=shift_id)
                counters["sent"] += 1
                
            except ValueError as e:
                # Expected errors (invalid data, missing info)
                logger.warning(f"Shift {shift_id}: skipped - {e}")
                counters["skipped"] += 1
                
            except Exception as e:
                # Unexpected errors
                logger.error(f"Shift {shift_id}: failed - {e}", exc_info=True)
                counters["failed"] += 1
        
        # Calculate duration
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds() * 1000
        counters["duration_ms"] = int(duration)
        
        # Log summary
        logger.info(
            f"Scheduler run complete: due={counters['due_found']}, "
            f"sent={counters['sent']}, failed={counters['failed']}, "
            f"skipped={counters['skipped']}, duration={counters['duration_ms']}ms"
        )
        
    except Exception as e:
        logger.error(f"Scheduler run failed: {e}", exc_info=True)
        counters["failed"] = counters["due_found"]
        raise
    
    return counters
