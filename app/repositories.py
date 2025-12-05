# repositories.py
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from appdb import get_session


class EventRepository:
    """אחראי על טבלת events"""

    def create_event(
        self,
        org_id: int,
        hall_id: int,
        name: str,
        event_date,  # date או string 'YYYY-MM-DD'
        show_time=None,
        load_in_time=None,
        event_type: str = "show",
        status: str = "draft",
        producer_contact_id: Optional[int] = None,
        technical_contact_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> int:
        query = text("""
            INSERT INTO events (
                org_id, hall_id, name, event_date,
                show_time, load_in_time,
                event_type, status,
                producer_contact_id, technical_contact_id,
                notes, created_at, updated_at
            )
            VALUES (
                :org_id, :hall_id, :name, :event_date,
                :show_time, :load_in_time,
                :event_type, :status,
                :producer_contact_id, :technical_contact_id,
                :notes, :now, :now
            )
            RETURNING event_id
        """)
        now = datetime.utcnow()

        with get_session() as session:
            result = session.execute(
                query,
                {
                    "org_id": org_id,
                    "hall_id": hall_id,
                    "name": name,
                    "event_date": event_date,
                    "show_time": show_time,
                    "load_in_time": load_in_time,
                    "event_type": event_type,
                    "status": status,
                    "producer_contact_id": producer_contact_id,
                    "technical_contact_id": technical_contact_id,
                    "notes": notes,
                    "now": now,
                },
            )
            event_id = result.scalar_one()
            return event_id

    def get_event_by_id(self, event_id: int):
        query = text("SELECT * FROM events WHERE event_id = :event_id")
        with get_session() as session:
            result = session.execute(query, {"event_id": event_id})
            # מחזיר dict במקום tuple
            row = result.mappings().first()
            return row


class ContactRepository:
    """אחראי על טבלת contacts"""

    def get_or_create_by_phone(
        self,
        org_id: int,
        phone: str,
        name: Optional[str] = None,
        role: Optional[str] = None,
    ) -> int:
        # קודם מנסה למצוא contact קיים
        select_q = text("""
            SELECT contact_id
            FROM contacts
            WHERE org_id = :org_id AND phone = :phone
        """)

        with get_session() as session:
            existing = session.execute(
                select_q,
                {"org_id": org_id, "phone": phone},
            ).scalar()

            if existing:
                return existing

            # אם לא קיים - יוצר חדש
            insert_q = text("""
                INSERT INTO contacts (org_id, name, phone, role, created_at)
                VALUES (:org_id, :name, :phone, :role, :now)
                RETURNING contact_id
            """)
            now = datetime.utcnow()

            result = session.execute(
                insert_q,
                {
                    "org_id": org_id,
                    "name": name or phone,
                    "phone": phone,
                    "role": role,
                    "now": now,
                },
            )
            contact_id = result.scalar_one()
            return contact_id


class ConversationRepository:
    """אחראי על טבלת conversations"""

    def get_open_conversation(
        self,
        org_id: int,
        event_id: int,
        contact_id: int,
    ):
        query = text("""
            SELECT *
            FROM conversations
            WHERE org_id = :org_id
              AND event_id = :event_id
              AND contact_id = :contact_id
              AND status IN ('open', 'waiting_for_reply')
            ORDER BY created_at DESC
            LIMIT 1
        """)
        with get_session() as session:
            result = session.execute(
                query,
                {
                    "org_id": org_id,
                    "event_id": event_id,
                    "contact_id": contact_id,
                },
            )
            return result.mappings().first()

    def create_conversation(
        self,
        org_id: int,
        event_id: int,
        contact_id: int,
        channel: str = "whatsapp",
        status: str = "open",
    ) -> int:
        query = text("""
            INSERT INTO conversations (
                org_id, event_id, contact_id,
                channel, status,
                created_at, updated_at
            )
            VALUES (
                :org_id, :event_id, :contact_id,
                :channel, :status,
                :now, :now
            )
            RETURNING conversation_id
        """)
        now = datetime.utcnow()

        with get_session() as session:
            result = session.execute(
                query,
                {
                    "org_id": org_id,
                    "event_id": event_id,
                    "contact_id": contact_id,
                    "channel": channel,
                    "status": status,
                    "now": now,
                },
            )
            conv_id = result.scalar_one()
            return conv_id


class MessageRepository:
    """אחראי על טבלת messages + עדכון last_message_id בשיחה"""

    def log_message(
        self,
        org_id: int,
        conversation_id: int,
        event_id: int,
        contact_id: int,
        direction: str,  # 'outgoing' / 'incoming'
        body: str,
        template_id: Optional[int] = None,
        whatsapp_msg_sid: Optional[str] = None,
        sent_at=None,
        received_at=None,
    ) -> int:
        msg_q = text("""
            INSERT INTO messages (
                org_id, conversation_id, event_id, contact_id,
                direction, template_id, body,
                whatsapp_msg_sid, sent_at, received_at,
                created_at
            )
            VALUES (
                :org_id, :conversation_id, :event_id, :contact_id,
                :direction, :template_id, :body,
                :whatsapp_msg_sid, :sent_at, :received_at,
                :now
            )
            RETURNING message_id
        """)

        now = datetime.utcnow()

        with get_session() as session:
            result = session.execute(
                msg_q,
                {
                    "org_id": org_id,
                    "conversation_id": conversation_id,
                    "event_id": event_id,
                    "contact_id": contact_id,
                    "direction": direction,
                    "template_id": template_id,
                    "body": body,
                    "whatsapp_msg_sid": whatsapp_msg_sid,
                    "sent_at": sent_at,
                    "received_at": received_at,
                    "now": now,
                },
            )
            message_id = result.scalar_one()

            # מעדכנים את last_message_id בשיחה
            update_conv_q = text("""
                UPDATE conversations
                SET last_message_id = :message_id,
                    updated_at = :now
                WHERE conversation_id = :conversation_id
            """)
            session.execute(
                update_conv_q,
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "now": now,
                },
            )

            return message_id
