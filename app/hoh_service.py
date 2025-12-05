# app/hoh_service.py
import json
import os
from datetime import datetime, timezone

from app.repositories import (
    EventRepository,
    ContactRepository,
    ConversationRepository,
    MessageRepository,
)
from app import twilio_client


class HOHService:
    def __init__(self):
        self.events = EventRepository()
        self.contacts = ContactRepository()
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()

    def create_event_with_producer_conversation(
        self,
        org_id: int,
        hall_id: int,
        event_name: str,
        event_date_str: str,
        show_time_str: str,
        producer_name: str,
        producer_phone: str,
    ):
        event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
        show_time = None
        if show_time_str:
            time_part = datetime.strptime(show_time_str, "%H:%M").time()
            show_time = datetime.combine(event_date, time_part).replace(tzinfo=timezone.utc)

        producer_contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id,
            phone=producer_phone,
            name=producer_name,
            role="producer",
        )

        event_id = self.events.create_event(
            org_id=org_id,
            hall_id=hall_id,
            name=event_name,
            event_date=event_date,
            show_time=show_time,
            status="pending_contact",
            producer_contact_id=producer_contact_id,
        )

        conv_id = self.conversations.create_conversation(
            org_id=org_id,
            event_id=event_id,
            contact_id=producer_contact_id,
            channel="whatsapp",
            status="open",
        )

        msg_id = self.messages.log_message(
            org_id=org_id,
            conversation_id=conv_id,
            event_id=event_id,
            contact_id=producer_contact_id,
            direction="outgoing",
            body="Conversation created",
        )

        return {
            "event_id": event_id,
            "contact_id": producer_contact_id,
            "conversation_id": conv_id,
            "message_id": msg_id,
        }

    def list_events_for_org(self, org_id: int):
        return self.events.list_events_for_org(org_id)

    async def send_init_for_event(self, event_id: int, org_id: int = 1) -> None:
        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        if not event:
            raise ValueError(f"Event {event_id} not found for org {org_id}")

        producer_contact_id = event.get("producer_contact_id")
        if not producer_contact_id:
            raise ValueError("Event missing producer_contact_id; cannot send INIT")

        contact = self.contacts.get_contact_by_id(
            org_id=org_id, contact_id=producer_contact_id
        )
        if not contact:
            raise ValueError(
                f"Producer contact {producer_contact_id} not found for org {org_id}"
            )

        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=producer_contact_id
        )
        if conversation:
            conversation_id = conversation["conversation_id"]
        else:
            conversation_id = self.conversations.create_conversation(
                org_id=org_id,
                event_id=event_id,
                contact_id=producer_contact_id,
                channel="whatsapp",
                status="open",
            )

        event_date = event.get("event_date")
        show_time = event.get("show_time")

        event_date_str = event_date.strftime("%d.%m.%Y") if event_date else ""
        show_time_str = show_time.strftime("%H:%M") if show_time else ""

        variables = {
            "producer_name": contact.get("name") or "Producer",
            "event_name": event.get("name") or "",
            "event_date": event_date_str,
            "show_time": show_time_str,
            "choose_time_action": f"CHOOSE_TIME_EVT_{event_id}",
            "not_contact_action": f"NOT_CONTACT_EVT_{event_id}",
            "no_times_action": f"NO_TIMES_EVT_{event_id}",
        }

        content_sid = os.getenv("CONTENT_SID_INIT_QR")
        if not content_sid:
            raise RuntimeError("Missing CONTENT_SID_INIT_QR env var for INIT message")

        twilio_response = twilio_client.send_content_message(
            to=contact.get("phone"),
            content_sid=content_sid,
            variables=variables,
            channel="whatsapp",
        )

        sent_at = datetime.now(timezone.utc)
        message_body = f"INIT sent with variables: {json.dumps(variables, ensure_ascii=False)}"
        whatsapp_sid = getattr(twilio_response, "sid", None)
        raw_payload = {
            "content_sid": content_sid,
            "variables": variables,
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=producer_contact_id,
            direction="outgoing",
            body=message_body,
            whatsapp_msg_sid=whatsapp_sid,
            sent_at=sent_at,
            raw_payload=raw_payload,
        )
