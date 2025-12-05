# app/hoh_service.py
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
        event_date: str,   # 'YYYY-MM-DD'
        producer_phone: str,
        producer_name: str,
        first_message_body: str,
    ):
        # 1. אירוע
        event_id = self.events.create_event(
            org_id=org_id,
            hall_id=hall_id,
            name=event_name,
            event_date=event_date,
        )

        # 2. איש קשר
        producer_contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id,
            phone=producer_phone,
            name=producer_name,
            role="producer",
        )

        # 3. שיחה
        conv_id = self.conversations.create_conversation(
            org_id=org_id,
            event_id=event_id,
            contact_id=producer_contact_id,
        )

        # 4. הודעה ראשונה
        msg_id = self.messages.log_message(
            org_id=org_id,
            conversation_id=conv_id,
            event_id=event_id,
            contact_id=producer_contact_id,
            direction="outgoing",
            body=first_message_body,
        )

        return {
            "event_id": event_id,
            "contact_id": producer_contact_id,
            "conversation_id": conv_id,
            "message_id": msg_id,
        }
