"""Scheduler service for running due followups."""

import logging
import time
from typing import Optional
from datetime import datetime

from app.hoh_service import HOHService
from app.repositories import OrgRepository
from app.appdb import get_session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for running scheduled followups across organizations."""
    
    def __init__(self):
        self.hoh = HOHService()
        self.orgs = OrgRepository()
    
    async def run_once(self, org_id: Optional[int] = None) -> dict:
        """
        Run the scheduler once for all orgs or a specific org.
        
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
                # Find due followups for this org
                from app.time_utils import now_utc
                now = now_utc()
                due_followups = self.hoh.messages.find_due_followups(
                    org_id=current_org_id, 
                    now=now
                )
                
                org_due_count = len(due_followups)
                due_found += org_due_count
                
                if org_due_count == 0:
                    continue
                
                # Process each due followup
                for item in due_followups:
                    try:
                        # Get required data
                        contact = self.hoh.contacts.get_contact_by_id(
                            org_id=current_org_id, contact_id=item.get("contact_id")
                        )
                        event = self.hoh.events.get_event_by_id(
                            org_id=current_org_id, event_id=item.get("event_id")
                        )
                        template = self.hoh.templates.get_template_by_id(
                            org_id=current_org_id, template_id=item.get("next_template_id")
                        )
                        
                        # Check if data is missing
                        if not contact or not event or not template:
                            skipped += 1
                            continue
                        
                        content_sid = template.get("content_sid")
                        if not content_sid:
                            skipped += 1
                            continue
                        
                        # Prepare message data
                        variables = self.hoh._build_followup_variables(
                            contact=contact, 
                            event=event
                        )
                        
                        from app.utils.phone import normalize_phone_to_e164_il
                        to_phone = normalize_phone_to_e164_il(
                            self.hoh._get_contact_value(contact, "phone")
                        )
                        
                        # Send the message
                        from app import twilio_client
                        twilio_response = twilio_client.send_content_message(
                            to=to_phone,
                            content_sid=content_sid,
                            content_variables=variables,
                            channel=template.get("channel", "whatsapp"),
                        )
                        
                        # Log the sent message
                        whatsapp_sid = getattr(twilio_response, "sid", None)
                        body = f"Followup sent via template {template.get('name') or template.get('template_id')}"
                        raw_payload = {
                            "content_sid": content_sid,
                            "variables": variables,
                            "followup_rule_id": item.get("rule_id"),
                            "twilio_message_sid": whatsapp_sid,
                        }
                        
                        self.hoh.messages.log_message(
                            org_id=current_org_id,
                            conversation_id=item.get("conversation_id"),
                            event_id=item.get("event_id"),
                            contact_id=item.get("contact_id"),
                            direction="outgoing",
                            template_id=item.get("next_template_id"),
                            body=body,
                            whatsapp_msg_sid=whatsapp_sid,
                            sent_at=now,
                            raw_payload=raw_payload,
                        )
                        
                        sent += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to send followup for org {current_org_id}: {e}")
                        failed += 1
                        
            except Exception as e:
                logger.error(f"Error processing org {current_org_id}: {e}")
                # Count all due items for this org as failed
                failed += len(due_followups) if 'due_followups' in locals() else 0
        
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
    
    def _get_all_org_ids(self) -> list[int]:
        """Get list of all org IDs."""
        with get_session() as session:
            result = session.execute(text("SELECT org_id FROM orgs ORDER BY org_id"))
            return [row[0] for row in result.fetchall()]
