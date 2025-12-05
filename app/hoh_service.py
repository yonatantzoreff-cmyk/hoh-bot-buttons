# app/hoh_service.py
from datetime import datetime, timezone

from app.repositories import (
    EventRepository,
    ContactRepository,
    ConversationRepository,
    MessageRepository,
)


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
