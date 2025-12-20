# repositories.py
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import json

from sqlalchemy import text

from .appdb import get_session
from .utils.phone import normalize_phone_to_e164_il
from .time_utils import now_utc


_NO_UPDATE = object()


class OrgRepository:
    """אחראי על טבלת orgs"""

    def get_org_by_id(self, org_id: int):
        query = text(
            """
            SELECT *
            FROM orgs
            WHERE org_id = :org_id
            """
        )
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id})
            return result.mappings().first()


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
        now = now_utc()

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

    def get_event_by_id(self, org_id: int, event_id: int):
        query = text(
            """
            SELECT *
            FROM events
            WHERE org_id = :org_id AND event_id = :event_id
            """
        )
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id, "event_id": event_id})
            # מחזיר dict במקום tuple
            row = result.mappings().first()
            return row

    def count_events_for_contact(self, org_id: int, contact_id: int) -> int:
        query = text(
            """
            SELECT COUNT(*) AS related_events
            FROM events
            WHERE org_id = :org_id
              AND (producer_contact_id = :contact_id OR technical_contact_id = :contact_id)
            """
        )

        with get_session() as session:
            result = session.execute(
                query, {"org_id": org_id, "contact_id": contact_id}
            ).scalar_one()
            return int(result)

    def update_event_fields(
        self,
        org_id: int,
        event_id: int,
        *,
        load_in_time=None,
        status: Optional[str] = None,
        producer_contact_id: Optional[int] = None,
        technical_contact_id: Optional[int] = None,
    ) -> None:
        sets = []
        params = {"org_id": org_id, "event_id": event_id, "now": now_utc()}

        if load_in_time is not None:
            sets.append("load_in_time = :load_in_time")
            params["load_in_time"] = load_in_time

        if status is not None:
            sets.append("status = :status")
            params["status"] = status

        if producer_contact_id is not None:
            sets.append("producer_contact_id = :producer_contact_id")
            params["producer_contact_id"] = producer_contact_id

        if technical_contact_id is not None:
            sets.append("technical_contact_id = :technical_contact_id")
            params["technical_contact_id"] = technical_contact_id

        if not sets:
            return

        sets.append("updated_at = :now")
        query = text(
            f"""
            UPDATE events
            SET {', '.join(sets)}
            WHERE org_id = :org_id AND event_id = :event_id
            """
        )

        with get_session() as session:
            session.execute(query, params)

    def update_event(
        self,
        org_id: int,
        event_id: int,
        *,
        hall_id: Optional[int] = _NO_UPDATE,
        name: Optional[str] = _NO_UPDATE,
        event_date=_NO_UPDATE,
        show_time=_NO_UPDATE,
        load_in_time=_NO_UPDATE,
        producer_contact_id: Optional[int] = _NO_UPDATE,
        technical_contact_id: Optional[int] = _NO_UPDATE,
        notes: Optional[str] = _NO_UPDATE,
    ) -> None:
        sets = ["updated_at = :now"]
        params = {"org_id": org_id, "event_id": event_id, "now": now_utc()}

        if hall_id is not _NO_UPDATE:
            sets.append("hall_id = :hall_id")
            params["hall_id"] = hall_id

        if name is not _NO_UPDATE:
            sets.append("name = :name")
            params["name"] = name

        if event_date is not _NO_UPDATE:
            sets.append("event_date = :event_date")
            params["event_date"] = event_date

        if show_time is not _NO_UPDATE:
            sets.append("show_time = :show_time")
            params["show_time"] = show_time

        if load_in_time is not _NO_UPDATE:
            sets.append("load_in_time = :load_in_time")
            params["load_in_time"] = load_in_time

        if producer_contact_id is not _NO_UPDATE:
            sets.append("producer_contact_id = :producer_contact_id")
            params["producer_contact_id"] = producer_contact_id

        if technical_contact_id is not _NO_UPDATE:
            sets.append("technical_contact_id = :technical_contact_id")
            params["technical_contact_id"] = technical_contact_id

        if notes is not _NO_UPDATE:
            sets.append("notes = :notes")
            params["notes"] = notes

        query = text(
            f"""
            UPDATE events
            SET {', '.join(sets)}
            WHERE org_id = :org_id AND event_id = :event_id
            """
        )

        with get_session() as session:
            session.execute(query, params)

    def clear_contact_references(self, org_id: int, contact_id: int) -> None:
        query = text(
            """
            UPDATE events
            SET producer_contact_id = CASE
                    WHEN producer_contact_id = :contact_id THEN NULL
                    ELSE producer_contact_id
                END,
                technical_contact_id = CASE
                    WHEN technical_contact_id = :contact_id THEN NULL
                    ELSE technical_contact_id
                END,
                updated_at = :now
            WHERE org_id = :org_id
              AND (producer_contact_id = :contact_id OR technical_contact_id = :contact_id)
            """
        )

        with get_session() as session:
            session.execute(
                query,
                {
                    "org_id": org_id,
                    "contact_id": contact_id,
                    "now": now_utc(),
                },
            )

    def list_events_for_org(self, org_id: int):
        query = text(
            """
            SELECT
                e.event_id,
                e.name,
                e.event_date,
                e.show_time,
                e.load_in_time,
                e.hall_id,
                h.name AS hall_name,
                e.notes,
                e.status,
                e.producer_contact_id,
                prod.name AS producer_name,
                prod.phone AS producer_phone,
                e.technical_contact_id,
                tech.name AS technical_name,
                tech.phone AS technical_phone,
                e.created_at
            FROM events e
            LEFT JOIN halls h ON e.hall_id = h.hall_id
            LEFT JOIN contacts prod
              ON e.org_id = prod.org_id AND e.producer_contact_id = prod.contact_id
            LEFT JOIN contacts tech
              ON e.org_id = tech.org_id AND e.technical_contact_id = tech.contact_id
            WHERE e.org_id = :org_id
            ORDER BY e.created_at ASC, e.event_id ASC
            """
        )

        with get_session() as session:
            result = session.execute(query, {"org_id": org_id})
            return result.mappings().all()

    def delete_event(self, org_id: int, event_id: int) -> None:
        query = text(
            """
            DELETE FROM events
            WHERE org_id = :org_id AND event_id = :event_id
            """
        )

        with get_session() as session:
            session.execute(query, {"org_id": org_id, "event_id": event_id})


class ContactRepository:
    """אחראי על טבלת contacts"""

    def list_contacts(self, org_id: int):
        query = text(
            """
            WITH event_links AS (
                SELECT org_id, contact_id, COUNT(*) AS event_usage_count
                FROM (
                    SELECT org_id, producer_contact_id AS contact_id
                    FROM events
                    WHERE producer_contact_id IS NOT NULL
                    UNION ALL
                    SELECT org_id, technical_contact_id AS contact_id
                    FROM events
                    WHERE technical_contact_id IS NOT NULL
                ) linked
                GROUP BY org_id, contact_id
            )
            SELECT
                c.contact_id,
                c.name,
                c.phone,
                c.role,
                c.created_at,
                COALESCE(el.event_usage_count, 0) AS event_usage_count
            FROM contacts c
            LEFT JOIN event_links el
              ON c.org_id = el.org_id AND c.contact_id = el.contact_id
            WHERE c.org_id = :org_id
            ORDER BY c.role, c.name
            """
        )

        with get_session() as session:
            result = session.execute(query, {"org_id": org_id})
            return result.mappings().all()

    def create_contact(self, org_id: int, name: str, phone: str, role: str) -> int:
        query = text(
            """
            INSERT INTO contacts (org_id, name, phone, role, created_at)
            VALUES (:org_id, :name, :phone, :role, :now)
            RETURNING contact_id
            """
        )

        with get_session() as session:
            result = session.execute(
                query,
                {
                    "org_id": org_id,
                    "name": name,
                    "phone": normalize_phone_to_e164_il(phone),
                    "role": role,
                    "now": now_utc(),
                },
            )
            return result.scalar_one()

    def get_or_create_by_phone(
        self,
        org_id: int,
        phone: str,
        name: Optional[str] = None,
        role: Optional[str] = None,
    ) -> int:
        """Return an existing contact_id for the normalized phone or create one."""
        normalized_phone = normalize_phone_to_e164_il(phone)

        select_q = text("""
            SELECT contact_id, phone
            FROM contacts
            WHERE org_id = :org_id AND phone = :phone
        """)

        with get_session() as session:
            existing = session.execute(
                select_q,
                {"org_id": org_id, "phone": normalized_phone},
            ).mappings().first()

            if not existing and phone != normalized_phone:
                existing = session.execute(
                    select_q,
                    {"org_id": org_id, "phone": phone},
                ).mappings().first()
                if existing and existing.get("phone") != normalized_phone:
                    session.execute(
                        text(
                            """
                            UPDATE contacts
                            SET phone = :normalized_phone
                            WHERE org_id = :org_id AND contact_id = :contact_id
                            """
                        ),
                        {
                            "normalized_phone": normalized_phone,
                            "org_id": org_id,
                            "contact_id": existing.get("contact_id"),
                        },
                    )

            if existing:
                return existing.get("contact_id")

            # אם לא קיים - יוצר חדש
            insert_q = text("""
                INSERT INTO contacts (org_id, name, phone, role, created_at)
                VALUES (:org_id, :name, :phone, :role, :now)
                RETURNING contact_id
            """)
            now = now_utc()

            result = session.execute(
                insert_q,
                {
                    "org_id": org_id,
                    "name": name or normalized_phone,
                    "phone": normalized_phone,
                    "role": role,
                    "now": now,
                },
            )
            contact_id = result.scalar_one()
            return contact_id

    def get_contact_by_id(self, org_id: int, contact_id: int):
        query = text(
            """
            SELECT *
            FROM contacts
            WHERE org_id = :org_id AND contact_id = :contact_id
            """
        )

        with get_session() as session:
            result = session.execute(
                query, {"org_id": org_id, "contact_id": contact_id}
            )
            return result.mappings().first()

    def delete_contact(self, org_id: int, contact_id: int) -> None:
        query = text(
            """
            DELETE FROM contacts
            WHERE org_id = :org_id AND contact_id = :contact_id
            """
        )

        with get_session() as session:
            session.execute(query, {"org_id": org_id, "contact_id": contact_id})

    def update_contact_phone(self, org_id: int, contact_id: int, phone: str) -> None:
        query = text(
            """
            UPDATE contacts
            SET phone = :phone
            WHERE org_id = :org_id AND contact_id = :contact_id
            """
        )

        with get_session() as session:
            session.execute(
                query,
                {
                    "phone": normalize_phone_to_e164_il(phone),
                    "org_id": org_id,
                    "contact_id": contact_id,
                },
            )

    def update_contact(
        self,
        org_id: int,
        contact_id: int,
        *,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
    ) -> None:
        sets = []
        params = {"org_id": org_id, "contact_id": contact_id}

        if name is not None:
            sets.append("name = :name")
            params["name"] = name

        if phone is not None:
            sets.append("phone = :phone")
            params["phone"] = normalize_phone_to_e164_il(phone)

        if role is not None:
            sets.append("role = :role")
            params["role"] = role

        if not sets:
            return

        query = text(
            f"""
            UPDATE contacts
            SET {', '.join(sets)}
            WHERE org_id = :org_id AND contact_id = :contact_id
            """
        )

        with get_session() as session:
            session.execute(query, params)

    def get_contact_by_phone(self, org_id: int, phone: str):
        """Return a contact mapping by phone (normalized or raw)."""

        normalized_phone = normalize_phone_to_e164_il(phone)

        base_query = text(
            """
            SELECT *
            FROM contacts
            WHERE org_id = :org_id AND phone = :phone
            """
        )

        with get_session() as session:
            result = session.execute(
                base_query, {"org_id": org_id, "phone": normalized_phone}
            ).mappings().first()

            if result or phone == normalized_phone:
                return result

            return session.execute(
                base_query, {"org_id": org_id, "phone": phone}
            ).mappings().first()


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

    def get_recent_open_for_contact(self, org_id: int, contact_id: int):
        query = text(
            """
            SELECT *
            FROM conversations
            WHERE org_id = :org_id
              AND contact_id = :contact_id
              AND status IN ('open', 'waiting_for_reply')
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )

        with get_session() as session:
            result = session.execute(
                query, {"org_id": org_id, "contact_id": contact_id}
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
        now = now_utc()

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

    def update_pending_data_fields(
        self,
        org_id: int,
        conversation_id: int,
        pending_data_fields,
        status: Optional[str] = None,
    ) -> None:
        if isinstance(pending_data_fields, dict):
            pending_data_fields = json.dumps(pending_data_fields, ensure_ascii=False)

        query = text(
            """
            UPDATE conversations
            SET pending_data_fields = :pending_data_fields,
                updated_at = :now
                {status_clause}
            WHERE org_id = :org_id AND conversation_id = :conversation_id
            """.format(
                status_clause=", status = :status" if status is not None else ""
            )
        )
        params = {
            "pending_data_fields": pending_data_fields,
            "org_id": org_id,
            "conversation_id": conversation_id,
            "now": now_utc(),
        }
        if status is not None:
            params["status"] = status

        with get_session() as session:
            session.execute(query, params)

    def update_status(self, org_id: int, conversation_id: int, status: str) -> None:
        query = text(
            """
            UPDATE conversations
            SET status = :status,
            updated_at = :now
            WHERE org_id = :org_id AND conversation_id = :conversation_id
            """
        )
        params = {
            "status": status,
            "org_id": org_id,
            "conversation_id": conversation_id,
            "now": now_utc(),
        }
        with get_session() as session:
            session.execute(query, params)

    def clear_last_message_for_event(self, org_id: int, event_id: int) -> None:
        query = text(
            """
            UPDATE conversations
            SET last_message_id = NULL
            WHERE org_id = :org_id AND event_id = :event_id
            """
        )

        with get_session() as session:
            session.execute(query, {"org_id": org_id, "event_id": event_id})

    def delete_by_event(self, org_id: int, event_id: int) -> None:
        query = text(
            """
            DELETE FROM conversations
            WHERE org_id = :org_id AND event_id = :event_id
            """
        )

        with get_session() as session:
            session.execute(query, {"org_id": org_id, "event_id": event_id})

    def clear_contact(self, org_id: int, contact_id: int) -> None:
        query = text(
            """
            UPDATE conversations
            SET contact_id = NULL,
                updated_at = :now
            WHERE org_id = :org_id AND contact_id = :contact_id
            """
        )

        with get_session() as session:
            session.execute(
                query,
                {
                    "org_id": org_id,
                    "contact_id": contact_id,
                    "now": now_utc(),
                },
            )


class MessageRepository:
    """אחראי על טבלת messages + עדכון last_message_id בשיחה"""

    def log_message(
        self,
        org_id: int,
        conversation_id: Optional[int],
        event_id: Optional[int],
        contact_id: Optional[int],
        direction: str,  # 'outgoing' / 'incoming'
        body: str,
        template_id: Optional[int] = None,
        whatsapp_msg_sid: Optional[str] = None,
        sent_at=None,
        received_at=None,
        raw_payload: Optional[dict | str] = None,
    ) -> int:
        now = now_utc()

        if isinstance(raw_payload, dict):
            raw_payload = json.dumps(raw_payload, ensure_ascii=False)

        if sent_at is None and direction == "outgoing":
            sent_at = now

        if received_at is None and direction == "incoming":
            received_at = now

        msg_q = text(
            """
            INSERT INTO messages (
                org_id, conversation_id, event_id, contact_id,
                direction, template_id, body,
                raw_payload, whatsapp_msg_sid, sent_at, received_at,
                created_at
            )
            VALUES (
                :org_id, :conversation_id, :event_id, :contact_id,
                :direction, :template_id, :body,
                :raw_payload, :whatsapp_msg_sid, :sent_at, :received_at,
                :now
            )
            RETURNING message_id
        """
        )

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
                    "raw_payload": raw_payload,
                    "whatsapp_msg_sid": whatsapp_msg_sid,
                    "sent_at": sent_at,
                    "received_at": received_at,
                    "now": now,
                },
            )
            message_id = result.scalar_one()

            if conversation_id is not None:
                update_conv_q = text(
                    """
                    UPDATE conversations
                    SET last_message_id = :message_id,
                        updated_at = :now
                    WHERE conversation_id = :conversation_id AND org_id = :org_id
                    """
                )
                session.execute(
                    update_conv_q,
                    {
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                        "org_id": org_id,
                        "now": now,
                    },
                )

            return message_id

    def delete_by_event(self, org_id: int, event_id: int) -> None:
        query = text(
            """
            DELETE FROM messages
            WHERE org_id = :org_id AND event_id = :event_id
            """
        )

        with get_session() as session:
            session.execute(query, {"org_id": org_id, "event_id": event_id})

    def clear_contact(self, org_id: int, contact_id: int) -> None:
        query = text(
            """
            UPDATE messages
            SET contact_id = NULL
            WHERE org_id = :org_id AND contact_id = :contact_id
            """
        )

        with get_session() as session:
            session.execute(query, {"org_id": org_id, "contact_id": contact_id})

    def find_due_followups(self, org_id: int, now: datetime) -> list[dict]:
        """
        Return a list of followups that should be sent now based on followup_rules
        and message history.
        """

        with get_session() as session:
            rules = session.execute(
                text(
                    """
                    SELECT *
                    FROM followup_rules
                    WHERE org_id = :org_id AND active = TRUE
                    """
                ),
                {"org_id": org_id},
            ).mappings().all()

            due: list[dict] = []

            for rule in rules:
                original_messages = session.execute(
                    text(
                        """
                        SELECT *
                        FROM messages
                        WHERE org_id = :org_id
                          AND direction = 'outgoing'
                          AND template_id = :from_template_id
                          AND sent_at IS NOT NULL
                        """
                    ),
                    {"org_id": org_id, "from_template_id": rule["from_template_id"]},
                ).mappings().all()

                for original in original_messages:
                    sent_at = original.get("sent_at")
                    if not sent_at:
                        continue

                    conversation_id = original.get("conversation_id")

                    incoming_reply = session.execute(
                        text(
                            """
                            SELECT 1
                            FROM messages
                            WHERE org_id = :org_id
                              AND conversation_id = :conversation_id
                              AND direction = 'incoming'
                              AND received_at IS NOT NULL
                              AND received_at > :sent_at
                            LIMIT 1
                            """
                        ),
                        {
                            "org_id": org_id,
                            "conversation_id": conversation_id,
                            "sent_at": sent_at,
                        },
                    ).first()

                    if incoming_reply:
                        continue

                    due_at = sent_at + timedelta(minutes=rule.get("delay_minutes", 0))
                    if now < due_at:
                        continue

                    attempts = session.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM messages
                            WHERE org_id = :org_id
                              AND conversation_id = :conversation_id
                              AND direction = 'outgoing'
                              AND template_id = :next_template_id
                              AND sent_at IS NOT NULL
                              AND sent_at > :sent_at
                            """
                        ),
                        {
                            "org_id": org_id,
                            "conversation_id": conversation_id,
                            "next_template_id": rule.get("next_template_id"),
                            "sent_at": sent_at,
                        },
                    ).scalar()

                    if attempts and attempts >= rule.get("max_attempts", 1):
                        continue

                    due.append(
                        {
                            "conversation_id": conversation_id,
                            "event_id": original.get("event_id"),
                            "contact_id": original.get("contact_id"),
                            "from_message_id": original.get("message_id"),
                            "from_template_id": rule.get("from_template_id"),
                            "rule_id": rule.get("rule_id"),
                            "next_template_id": rule.get("next_template_id"),
                        }
                    )

            return due

    def get_last_sent_at_for_content(
        self, org_id: int, event_id: int, content_sid: str
    ) -> Optional[datetime]:
        query = text(
            """
            SELECT MAX(sent_at) AS last_sent_at
            FROM messages
            WHERE org_id = :org_id
              AND event_id = :event_id
              AND direction = 'outgoing'
              AND raw_payload::json ->> 'content_sid' = :content_sid
            """
        )

        with get_session() as session:
            result = session.execute(
                query,
                {
                    "org_id": org_id,
                    "event_id": event_id,
                    "content_sid": content_sid,
                },
            ).mappings().first()

            return result.get("last_sent_at") if result else None

    def list_messages_with_events(self, org_id: int) -> list[dict]:
        query = text(
            """
            SELECT
                m.message_id,
                m.event_id,
                e.name AS event_name,
                e.event_date,
                e.show_time,
                m.direction,
                m.body,
                m.sent_at,
                m.received_at,
                m.created_at,
                c.name AS contact_name,
                c.phone AS contact_phone,
                latest_delivery.status AS delivery_status
            FROM messages m
            LEFT JOIN events e ON m.event_id = e.event_id
            LEFT JOIN contacts c ON m.contact_id = c.contact_id
            LEFT JOIN LATERAL (
                SELECT status
                FROM message_delivery_log
                WHERE message_id = m.message_id
                ORDER BY created_at DESC
                LIMIT 1
            ) latest_delivery ON true
            WHERE m.org_id = :org_id
            ORDER BY COALESCE(e.created_at, m.created_at) ASC,
                     COALESCE(m.sent_at, m.received_at, m.created_at) ASC,
                     m.message_id ASC
            """
        )

        with get_session() as session:
            result = session.execute(query, {"org_id": org_id})
            return result.mappings().all()

    def get_latest_status_by_event(self, org_id: int) -> dict[int, Optional[str]]:
        """Return the latest delivery status for each event with messages."""

        query = text(
            """
            WITH latest_messages AS (
                SELECT
                    event_id,
                    message_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY event_id
                        ORDER BY COALESCE(sent_at, received_at, created_at) DESC, message_id DESC
                    ) AS rn
                FROM messages
                WHERE org_id = :org_id
                  AND event_id IS NOT NULL
            )
            SELECT lm.event_id, mdl.status
            FROM latest_messages lm
            LEFT JOIN LATERAL (
                SELECT status
                FROM message_delivery_log
                WHERE org_id = :org_id AND message_id = lm.message_id
                ORDER BY created_at DESC, delivery_id DESC
                LIMIT 1
            ) mdl ON true
            WHERE lm.rn = 1
            """
        )

        with get_session() as session:
            result = session.execute(query, {"org_id": org_id}).mappings().all()

        return {row["event_id"]: row.get("status") for row in result}

    def get_message_by_whatsapp_sid(self, whatsapp_msg_sid: str):
        """
        Find a message by its Twilio WhatsApp Message SID.
        Returns the message row or None.
        """
        query = text(
            """
            SELECT *
            FROM messages
            WHERE whatsapp_msg_sid = :whatsapp_msg_sid
            LIMIT 1
            """
        )

        with get_session() as session:
            result = session.execute(query, {"whatsapp_msg_sid": whatsapp_msg_sid})
            return result.mappings().first()

    def update_message_timestamps_from_status(
        self, message_sid: str, status: str, occurred_at: datetime | None = None
    ) -> bool:
        """
        Update stored message status/timestamps based on Twilio status callback.
        Returns True if a DB row was updated, False if no message row exists for message_sid.
        Must NOT raise if message not found.
        """

        if not message_sid:
            return False

        when = occurred_at or now_utc()
        status_lower = (status or "").lower()

        with get_session() as session:
            # Detect which column stores the Twilio SID
            columns = set(
                session.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'messages'
                          AND column_name IN (
                              'twilio_message_sid', 'whatsapp_msg_sid',
                              'status', 'sent_at', 'delivered_at', 'read_at', 'failed_at', 'last_status_at'
                          )
                        """
                    )
                ).scalars()
            )

            sid_column = None
            if "twilio_message_sid" in columns:
                sid_column = "twilio_message_sid"
            elif "whatsapp_msg_sid" in columns:
                sid_column = "whatsapp_msg_sid"

            if sid_column is None:
                return False

            message = session.execute(
                text(
                    f"""
                    SELECT message_id
                    FROM messages
                    WHERE {sid_column} = :message_sid
                    LIMIT 1
                    """
                ),
                {"message_sid": message_sid},
            ).mappings().first()

            if not message:
                return False

            updates: dict[str, Any] = {"status": status, "last_status_at": when}

            if status_lower in {"queued", "accepted", "sent", "sending"}:
                updates["sent_at"] = when

            if status_lower == "delivered":
                updates["delivered_at"] = when

            if status_lower == "read":
                updates["read_at"] = when

            if status_lower in {"failed", "undelivered"}:
                updates["failed_at"] = when

            set_parts = []
            params: dict[str, Any] = {"message_id": message.get("message_id")}

            for column in ("status", "sent_at", "delivered_at", "read_at", "failed_at", "last_status_at"):
                if column not in columns or updates.get(column) is None:
                    continue

                params[column] = updates[column]

                if column == "sent_at":
                    set_parts.append("sent_at = COALESCE(sent_at, :sent_at)")
                else:
                    set_parts.append(f"{column} = :{column}")

            if not set_parts:
                return True

            query = text(
                f"""
                UPDATE messages
                SET {', '.join(set_parts)}
                WHERE message_id = :message_id
                """
            )

            session.execute(query, params)

            return True

    def get_unread_summary(self, org_id: int, user_id: str = "admin", limit: int = 5) -> dict:
        """
        Get notification summary with unread count and recent events with new messages.
        Returns up to `limit` events with their latest message info.
        """
        query = text(
            """
            WITH user_state AS (
                SELECT COALESCE(last_seen_message_id, 0) AS last_seen_id,
                       COALESCE(last_seen_at, '1970-01-01'::timestamptz) AS last_seen_time
                FROM user_notification_state
                WHERE org_id = :org_id AND user_id = :user_id
            ),
            unread_messages AS (
                SELECT m.message_id, m.event_id, m.received_at, m.body
                FROM messages m
                CROSS JOIN user_state us
                WHERE m.org_id = :org_id
                  AND m.direction = 'incoming'
                  AND (m.message_id > us.last_seen_id OR m.received_at > us.last_seen_time)
            ),
            latest_incoming_messages AS (
                SELECT DISTINCT ON (event_id)
                    event_id,
                    body AS last_message_snippet
                FROM messages
                WHERE org_id = :org_id AND direction = 'incoming'
                ORDER BY event_id, received_at DESC
            ),
            event_summary AS (
                SELECT 
                    e.event_id,
                    e.name AS event_name,
                    e.event_date,
                    h.name AS hall_name,
                    h.hall_id,
                    COUNT(um.message_id) AS unread_count,
                    MAX(um.received_at) AS last_message_at,
                    lim.last_message_snippet
                FROM unread_messages um
                JOIN events e ON um.event_id = e.event_id
                LEFT JOIN halls h ON e.hall_id = h.hall_id
                LEFT JOIN latest_incoming_messages lim ON e.event_id = lim.event_id
                GROUP BY e.event_id, e.name, e.event_date, h.name, h.hall_id, lim.last_message_snippet
                ORDER BY MAX(um.received_at) DESC
                LIMIT :limit
            )
            SELECT 
                (SELECT COUNT(*) FROM unread_messages) AS unread_count_total,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'event_id', es.event_id,
                            'event_name', es.event_name,
                            'event_date', es.event_date,
                            'hall_id', es.hall_id,
                            'hall_name', es.hall_name,
                            'unread_count_for_event', es.unread_count,
                            'last_message_snippet', LEFT(es.last_message_snippet, 100),
                            'last_message_at', es.last_message_at
                        )
                    ) FILTER (WHERE es.event_id IS NOT NULL),
                    '[]'::json
                ) AS items
            FROM event_summary es
            """
        )
        
        with get_session() as session:
            result = session.execute(query, {
                "org_id": org_id,
                "user_id": user_id,
                "limit": limit
            }).mappings().first()
            
            if result:
                return {
                    "unread_count_total": result["unread_count_total"] or 0,
                    "items": result["items"] if result["items"] else []
                }
            return {"unread_count_total": 0, "items": []}

    def get_recent_messages_with_events(self, org_id: int, limit: int = 200) -> list[dict]:
        """
        Get recent messages with event details for the full messages view.
        """
        query = text(
            """
            SELECT
                m.message_id,
                m.event_id,
                e.name AS event_name,
                e.event_date,
                e.show_time,
                h.name AS hall_name,
                m.direction,
                m.body,
                m.sent_at,
                m.received_at,
                m.created_at,
                c.name AS contact_name,
                c.phone AS contact_phone
            FROM messages m
            LEFT JOIN events e ON m.event_id = e.event_id
            LEFT JOIN halls h ON e.hall_id = h.hall_id
            LEFT JOIN contacts c ON m.contact_id = c.contact_id
            WHERE m.org_id = :org_id
            ORDER BY COALESCE(m.received_at, m.sent_at, m.created_at) DESC
            LIMIT :limit
            """
        )
        
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id, "limit": limit})
            return result.mappings().all()

    def mark_all_as_read(self, org_id: int, user_id: str = "admin") -> None:
        """
        Mark all messages as read by updating the user's last_seen state.
        """
        # Use a CTE to compute max_message_id once
        query = text(
            """
            WITH max_msg AS (
                SELECT COALESCE(MAX(message_id), 0) AS max_id FROM messages WHERE org_id = :org_id
            )
            INSERT INTO user_notification_state (org_id, user_id, last_seen_message_id, last_seen_at, updated_at)
            SELECT :org_id, :user_id, max_id, NOW(), NOW() FROM max_msg
            ON CONFLICT (org_id, user_id)
            DO UPDATE SET 
                last_seen_message_id = (SELECT max_id FROM max_msg),
                last_seen_at = NOW(),
                updated_at = NOW()
            """
        )
        
        with get_session() as session:
            session.execute(query, {"org_id": org_id, "user_id": user_id})


class TemplateRepository:
    """אחראי על טבלאות message_templates / followup_rules."""

    def get_template_by_id(self, org_id: int, template_id: int):
        query = text(
            """
            SELECT *
            FROM message_templates
            WHERE org_id = :org_id AND template_id = :template_id
            """
        )

        with get_session() as session:
            result = session.execute(
                query, {"org_id": org_id, "template_id": template_id}
            )
            return result.mappings().first()

    def get_followup_rule_by_id(self, org_id: int, rule_id: int):
        query = text(
            """
            SELECT *
            FROM followup_rules
            WHERE org_id = :org_id AND rule_id = :rule_id
            """
        )

        with get_session() as session:
            result = session.execute(query, {"org_id": org_id, "rule_id": rule_id})
            return result.mappings().first()


class MessageDeliveryLogRepository:
    """אחראי על טבלת message_delivery_log - Twilio delivery status tracking."""

    def create_delivery_log(
        self,
        org_id: int,
        message_id: int,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        provider: str = "twilio",
        provider_payload: Optional[dict] = None,
    ) -> int:
        """
        Insert a new delivery log entry.
        Returns the delivery_id of the newly created row.
        """
        payload_json = None
        if provider_payload:
            try:
                payload_json = json.dumps(provider_payload, ensure_ascii=False)
            except (TypeError, ValueError) as e:
                # Log error but don't fail the entire operation
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to serialize provider_payload", exc_info=e
                )
                payload_json = json.dumps({"error": "serialization_failed"})
        
        provider_payload = payload_json

        query = text(
            """
            INSERT INTO message_delivery_log (
                org_id, message_id, status,
                error_code, error_message,
                provider, provider_payload, created_at
            )
            VALUES (
                :org_id, :message_id, :status,
                :error_code, :error_message,
                :provider, :provider_payload, :now
            )
            RETURNING delivery_id
            """
        )

        with get_session() as session:
            result = session.execute(
                query,
                {
                    "org_id": org_id,
                    "message_id": message_id,
                    "status": status,
                    "error_code": error_code,
                    "error_message": error_message,
                    "provider": provider,
                    "provider_payload": provider_payload,
                    "now": now_utc(),
                },
            )
            return result.scalar_one()

    def get_message_by_whatsapp_sid(self, whatsapp_msg_sid: str):
        """
        Find a message by its Twilio WhatsApp Message SID.
        Returns the message row or None.
        """
        query = text(
            """
            SELECT *
            FROM messages
            WHERE whatsapp_msg_sid = :whatsapp_msg_sid
            LIMIT 1
            """
        )

        with get_session() as session:
            result = session.execute(query, {"whatsapp_msg_sid": whatsapp_msg_sid})
            return result.mappings().first()


class EmployeeRepository:
    """אחראי על טבלת employees"""

    def create_employee(
        self,
        org_id: int,
        name: str,
        phone: str,
        role: Optional[str] = None,
        notes: Optional[str] = None,
        is_active: bool = True,
    ) -> int:
        """יוצר עובד חדש ומחזיר employee_id"""
        q = text("""
            INSERT INTO employees (org_id, name, phone, role, notes, is_active)
            VALUES (:org_id, :name, :phone, :role, :notes, :is_active)
            RETURNING employee_id
        """)

        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "name": name,
                    "phone": phone,
                    "role": role,
                    "notes": notes,
                    "is_active": is_active,
                },
            )
            employee_id = res.scalar_one()
            session.commit()
            return employee_id

    def get_employee_by_id(self, org_id: int, employee_id: int):
        """מחזיר עובד לפי employee_id, או None אם לא נמצא"""
        q = text("""
            SELECT *
            FROM employees
            WHERE org_id = :org_id
              AND employee_id = :employee_id
        """)

        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "employee_id": employee_id,
                },
            )
            row = res.mappings().first()
            return dict(row) if row else None

    def get_employee_by_phone(self, org_id: int, phone: str):
        """מחזיר עובד לפי טלפון בתוך אותו org, או None"""
        q = text("""
            SELECT *
            FROM employees
            WHERE org_id = :org_id
              AND phone = :phone
        """)

        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "phone": phone,
                },
            )
            row = res.mappings().first()
            return dict(row) if row else None

    def list_employees(self, org_id: int, active_only: bool = True):
        """מחזיר רשימת עובדים בארגון, עם אופציה לסנן לפי is_active"""
        base_sql = """
            SELECT *
            FROM employees
            WHERE org_id = :org_id
        """

        if active_only:
            base_sql += " AND is_active = TRUE"

        base_sql += " ORDER BY name"

        q = text(base_sql)

        with get_session() as session:
            res = session.execute(q, {"org_id": org_id})
            return [dict(r) for r in res.mappings().all()]

    def set_active(self, org_id: int, employee_id: int, is_active: bool):
        """הפעלה/הקפאת עובד"""
        q = text("""
            UPDATE employees
            SET is_active = :is_active
            WHERE org_id = :org_id
              AND employee_id = :employee_id
        """)

        with get_session() as session:
            session.execute(
                q,
                {
                    "org_id": org_id,
                    "employee_id": employee_id,
                    "is_active": is_active,
                },
            )
            session.commit()

    def update_employee(
        self,
        org_id: int,
        employee_id: int,
        *,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
        notes: Optional[str] = None,
    ):
        """עדכון פרטי עובד"""
        sets = []
        params = {"org_id": org_id, "employee_id": employee_id}

        if name is not None:
            sets.append("name = :name")
            params["name"] = name

        if phone is not None:
            sets.append("phone = :phone")
            params["phone"] = phone

        if role is not None:
            sets.append("role = :role")
            params["role"] = role

        if notes is not None:
            sets.append("notes = :notes")
            params["notes"] = notes

        if not sets:
            return

        q = text(f"""
            UPDATE employees
            SET {', '.join(sets)}
            WHERE org_id = :org_id
              AND employee_id = :employee_id
        """)

        with get_session() as session:
            session.execute(q, params)
            session.commit()

    def soft_delete_employee(self, org_id: int, employee_id: int):
        """מחיקה רכה של עובד (is_active=false)"""
        self.set_active(org_id=org_id, employee_id=employee_id, is_active=False)


class EmployeeShiftRepository:
    """אחראי על טבלת employee_shifts (שיוך משמרות לאירועים ולעובדים)"""

    def create_shift(
        self,
        org_id: int,
        event_id: int,
        employee_id: Optional[int],  # PHASE 2: Make nullable to allow empty shifts
        call_time,
        shift_role: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        יוצר משמרת חדשה לעובד באירוע מסוים.
        call_time = datetime (timezone-aware) לשעת כניסה.
        PHASE 2: employee_id can be None for unassigned shifts.
        """
        q = text("""
            INSERT INTO employee_shifts (
                org_id,
                event_id,
                employee_id,
                call_time,
                shift_role,
                notes
            )
            VALUES (:org_id, :event_id, :employee_id, :call_time, :shift_role, :notes)
            RETURNING shift_id
        """)

        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "event_id": event_id,
                    "employee_id": employee_id,  # Can be None
                    "call_time": call_time,
                    "shift_role": shift_role,
                    "notes": notes,
                },
            )
            shift_id = res.scalar_one()
            session.commit()
            return shift_id

    def list_shifts_for_event(self, org_id: int, event_id: int):
        """רשימת כל המשמרות באירוע מסוים (PHASE 2: Handles unassigned shifts)"""
        q = text("""
            SELECT s.*, 
                   COALESCE(e.name, '(Unassigned)') AS employee_name, 
                   e.phone AS employee_phone
            FROM employee_shifts s
            LEFT JOIN employees e
              ON e.employee_id = s.employee_id
             AND e.org_id = s.org_id
            WHERE s.org_id = :org_id
              AND s.event_id = :event_id
            ORDER BY s.call_time, COALESCE(e.name, 'ZZZZ')
        """)

        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "event_id": event_id,
                },
            )
            return [dict(r) for r in res.mappings().all()]

    def list_shifts_for_employee(self, org_id: int, employee_id: int):
        """רשימת כל המשמרות של עובד מסוים (כולל פרטי האירוע)"""
        q = text("""
            SELECT s.*, ev.name AS event_name, ev.show_time, ev.event_date
            FROM employee_shifts s
            JOIN events ev
              ON ev.event_id = s.event_id
             AND ev.org_id = s.org_id
            WHERE s.org_id = :org_id
              AND s.employee_id = :employee_id
            ORDER BY s.call_time DESC
        """)

        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "employee_id": employee_id,
                },
            )
            return [dict(r) for r in res.mappings().all()]

    def mark_24h_reminder_sent(self, shift_id: int, when=None):
        """מסמן שנשלחה תזכורת 24 שעות למשמרת"""
        if when is None:
            when = now_utc()

        q = text("""
            UPDATE employee_shifts
            SET reminder_24h_sent_at = :when,
                updated_at = :when
            WHERE shift_id = :shift_id
        """)

        with get_session() as session:
            session.execute(
                q,
                {
                    "shift_id": shift_id,
                    "when": when,
                },
            )
            session.commit()

    def get_shift_by_id(self, org_id: int, shift_id: int):
        """מחזיר משמרת לפי shift_id"""
        q = text("""
            SELECT s.*, e.name AS employee_name, e.phone AS employee_phone
            FROM employee_shifts s
            JOIN employees e
              ON e.employee_id = s.employee_id
             AND e.org_id = s.org_id
            WHERE s.org_id = :org_id
              AND s.shift_id = :shift_id
        """)

        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "shift_id": shift_id,
                },
            )
            row = res.mappings().first()
            return dict(row) if row else None

    def update_shift(
        self,
        org_id: int,
        shift_id: int,
        *,
        employee_id: Optional[int] = None,
        call_time=None,
        shift_role: Optional[str] = None,
        notes: Optional[str] = None,
    ):
        """עדכון משמרת קיימת"""
        sets = ["updated_at = :now"]
        params = {
            "org_id": org_id,
            "shift_id": shift_id,
            "now": now_utc(),
        }

        if employee_id is not None:
            sets.append("employee_id = :employee_id")
            params["employee_id"] = employee_id

        if call_time is not None:
            sets.append("call_time = :call_time")
            params["call_time"] = call_time

        if shift_role is not None:
            sets.append("shift_role = :shift_role")
            params["shift_role"] = shift_role

        if notes is not None:
            sets.append("notes = :notes")
            params["notes"] = notes

        if len(sets) == 1:  # רק updated_at
            return

        q = text(f"""
            UPDATE employee_shifts
            SET {', '.join(sets)}
            WHERE org_id = :org_id
              AND shift_id = :shift_id
        """)

        with get_session() as session:
            session.execute(q, params)
            session.commit()

    def delete_shift(self, org_id: int, shift_id: int):
        """מחיקה מוחלטת של משמרת"""
        q = text("""
            DELETE FROM employee_shifts
            WHERE org_id = :org_id
              AND shift_id = :shift_id
        """)

        with get_session() as session:
            session.execute(q, {"org_id": org_id, "shift_id": shift_id})
            session.commit()

    def get_shifts_for_month(
        self,
        org_id: int,
        year: int,
        month: int,
    ) -> list[dict]:
        """מחזיר משמרות בחודש מסוים (כולל יום לפני ויום אחרי לחישובי מנוחה)"""
        from datetime import date
        from calendar import monthrange
        
        start_date = date(year, month, 1)
        _, last_day = monthrange(year, month)
        end_date = date(year, month, last_day)
        
        # Expand range by 1 day before and after for rest calculations
        from datetime import datetime as dt, time, timedelta
        from zoneinfo import ZoneInfo
        
        israel_tz = ZoneInfo("Asia/Jerusalem")
        start_dt = dt.combine(start_date - timedelta(days=1), time.min).replace(tzinfo=israel_tz)
        end_dt = dt.combine(end_date + timedelta(days=1), time.max).replace(tzinfo=israel_tz)
        
        q = text("""
            SELECT 
                s.*,
                e.name AS employee_name,
                e.phone AS employee_phone,
                ev.name AS event_name,
                ev.event_date,
                ev.show_time,
                ev.load_in_time
            FROM employee_shifts s
            JOIN employees e ON e.employee_id = s.employee_id AND e.org_id = s.org_id
            JOIN events ev ON ev.event_id = s.event_id AND ev.org_id = s.org_id
            WHERE s.org_id = :org_id
              AND (s.start_at IS NULL OR s.start_at <= :end_dt)
              AND (s.call_time >= :start_dt OR s.end_at >= :start_dt)
            ORDER BY s.call_time, e.name
        """)
        
        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                },
            )
            return [dict(r) for r in res.mappings().all()]

    def upsert_shift(
        self,
        org_id: int,
        event_id: int,
        employee_id: int,
        start_at: datetime,
        end_at: datetime,
        shift_type: Optional[str] = None,
        is_locked: bool = False,
        shift_id: Optional[int] = None,
    ) -> int:
        """יוצר או מעדכן משמרת. אם shift_id מסופק - מעדכן, אחרת יוצר חדש"""
        now = now_utc()
        
        if shift_id:
            # Update existing shift
            q = text("""
                UPDATE employee_shifts
                SET employee_id = :employee_id,
                    start_at = :start_at,
                    end_at = :end_at,
                    call_time = :start_at,
                    shift_type = :shift_type,
                    is_locked = :is_locked,
                    updated_at = :now
                WHERE org_id = :org_id
                  AND shift_id = :shift_id
                RETURNING shift_id
            """)
            
            with get_session() as session:
                res = session.execute(
                    q,
                    {
                        "org_id": org_id,
                        "shift_id": shift_id,
                        "employee_id": employee_id,
                        "start_at": start_at,
                        "end_at": end_at,
                        "shift_type": shift_type,
                        "is_locked": is_locked,
                        "now": now,
                    },
                )
                session.commit()
                return res.scalar_one()
        else:
            # Create new shift
            q = text("""
                INSERT INTO employee_shifts (
                    org_id, event_id, employee_id,
                    start_at, end_at, call_time,
                    shift_type, is_locked,
                    created_at, updated_at
                )
                VALUES (
                    :org_id, :event_id, :employee_id,
                    :start_at, :end_at, :start_at,
                    :shift_type, :is_locked,
                    :now, :now
                )
                RETURNING shift_id
            """)
            
            with get_session() as session:
                res = session.execute(
                    q,
                    {
                        "org_id": org_id,
                        "event_id": event_id,
                        "employee_id": employee_id,
                        "start_at": start_at,
                        "end_at": end_at,
                        "shift_type": shift_type,
                        "is_locked": is_locked,
                        "now": now,
                    },
                )
                session.commit()
                return res.scalar_one()

    def delete_shifts_for_event(self, org_id: int, event_id: int, keep_locked: bool = True) -> None:
        """מחיקת כל המשמרות לאירוע (אופציה לשמור משמרות נעולות)"""
        if keep_locked:
            q = text("""
                DELETE FROM employee_shifts
                WHERE org_id = :org_id
                  AND event_id = :event_id
                  AND (is_locked = FALSE OR is_locked IS NULL)
            """)
        else:
            q = text("""
                DELETE FROM employee_shifts
                WHERE org_id = :org_id
                  AND event_id = :event_id
            """)
        
        with get_session() as session:
            session.execute(q, {"org_id": org_id, "event_id": event_id})
            session.commit()


class EmployeeUnavailabilityRepository:
    """אחראי על טבלת employee_unavailability (אי-זמינות עובדים)"""

    def create_unavailability(
        self,
        org_id: int,
        employee_id: int,
        start_at: datetime,
        end_at: datetime,
        note: Optional[str] = None,
    ) -> int:
        """יוצר בלוק אי-זמינות חדש ומחזיר unavailability_id"""
        q = text("""
            INSERT INTO employee_unavailability (
                org_id, employee_id, start_at, end_at, note, created_at, updated_at
            )
            VALUES (:org_id, :employee_id, :start_at, :end_at, :note, :now, :now)
            RETURNING unavailability_id
        """)
        
        now = now_utc()
        
        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "employee_id": employee_id,
                    "start_at": start_at,
                    "end_at": end_at,
                    "note": note,
                    "now": now,
                },
            )
            unavailability_id = res.scalar_one()
            session.commit()
            return unavailability_id

    def get_unavailability_for_month(
        self,
        org_id: int,
        year: int,
        month: int,
    ) -> list[dict]:
        """מחזיר את כל בלוקי האי-זמינות בחודש מסוים"""
        from datetime import date
        from calendar import monthrange
        
        start_date = date(year, month, 1)
        _, last_day = monthrange(year, month)
        end_date = date(year, month, last_day)
        
        # Convert to timezone-aware datetime (start of day and end of day in UTC)
        from datetime import datetime as dt, time
        from zoneinfo import ZoneInfo
        
        israel_tz = ZoneInfo("Asia/Jerusalem")
        start_dt = dt.combine(start_date, time.min).replace(tzinfo=israel_tz)
        end_dt = dt.combine(end_date, time.max).replace(tzinfo=israel_tz)
        
        q = text("""
            SELECT u.*, e.name AS employee_name, e.phone AS employee_phone
            FROM employee_unavailability u
            JOIN employees e ON e.employee_id = u.employee_id AND e.org_id = u.org_id
            WHERE u.org_id = :org_id
              AND u.start_at <= :end_dt
              AND u.end_at >= :start_dt
            ORDER BY u.start_at, e.name
        """)
        
        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                },
            )
            return [dict(r) for r in res.mappings().all()]

    def get_unavailability_for_employee(
        self,
        org_id: int,
        employee_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict]:
        """מחזיר אי-זמינות לעובד בטווח זמן מסוים"""
        q = text("""
            SELECT *
            FROM employee_unavailability
            WHERE org_id = :org_id
              AND employee_id = :employee_id
              AND start_at < :end_at
              AND end_at > :start_at
            ORDER BY start_at
        """)
        
        with get_session() as session:
            res = session.execute(
                q,
                {
                    "org_id": org_id,
                    "employee_id": employee_id,
                    "start_at": start_at,
                    "end_at": end_at,
                },
            )
            return [dict(r) for r in res.mappings().all()]

    def delete_unavailability(self, org_id: int, unavailability_id: int) -> None:
        """מחיקת בלוק אי-זמינות"""
        q = text("""
            DELETE FROM employee_unavailability
            WHERE org_id = :org_id
              AND unavailability_id = :unavailability_id
        """)
        
        with get_session() as session:
            session.execute(q, {"org_id": org_id, "unavailability_id": unavailability_id})
            session.commit()


class StagingEventRepository:
    """Repository for staging_events table (calendar import)"""

    def clear_all(self, org_id: int) -> None:
        """Delete all staging events for an org."""
        query = text("""
            DELETE FROM staging_events
            WHERE org_id = :org_id
        """)
        
        with get_session() as session:
            session.execute(query, {"org_id": org_id})

    def bulk_insert(self, org_id: int, events: list[dict]) -> None:
        """Insert multiple staging events in a single transaction."""
        query = text("""
            INSERT INTO staging_events (
                org_id, row_index, date, show_time, name, load_in,
                event_series, producer_name, producer_phone, notes,
                is_valid, errors_json, warnings_json, created_at, updated_at
            )
            VALUES (
                :org_id, :row_index, :date, :show_time, :name, :load_in,
                :event_series, :producer_name, :producer_phone, :notes,
                :is_valid, :errors_json, :warnings_json, :now, :now
            )
        """)
        
        now = now_utc()
        
        with get_session() as session:
            for event in events:
                session.execute(query, {
                    "org_id": org_id,
                    "row_index": event.get("row_index"),
                    "date": event.get("date"),
                    "show_time": event.get("show_time"),
                    "name": event.get("name"),
                    "load_in": event.get("load_in"),
                    "event_series": event.get("event_series"),
                    "producer_name": event.get("producer_name"),
                    "producer_phone": event.get("producer_phone"),
                    "notes": event.get("notes"),
                    "is_valid": event.get("is_valid", False),
                    "errors_json": json.dumps(event.get("errors", []), ensure_ascii=False),
                    "warnings_json": json.dumps(event.get("warnings", []), ensure_ascii=False),
                    "now": now,
                })

    def list_all(self, org_id: int) -> list[dict]:
        """Get all staging events for an org."""
        query = text("""
            SELECT *
            FROM staging_events
            WHERE org_id = :org_id
            ORDER BY row_index ASC
        """)
        
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id})
            return [dict(row) for row in result.mappings().all()]

    def get_by_id(self, org_id: int, staging_id: int) -> Optional[dict]:
        """Get a single staging event."""
        query = text("""
            SELECT *
            FROM staging_events
            WHERE org_id = :org_id AND id = :id
        """)
        
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id, "id": staging_id})
            row = result.mappings().first()
            return dict(row) if row else None

    def update(self, org_id: int, staging_id: int, fields: dict) -> None:
        """Update specific fields in a staging event."""
        sets = ["updated_at = :now"]
        params = {"org_id": org_id, "id": staging_id, "now": now_utc()}
        
        # Allow updating these fields
        allowed_fields = [
            "date", "show_time", "name", "load_in", "event_series",
            "producer_name", "producer_phone", "notes",
            "is_valid", "errors_json", "warnings_json"
        ]
        
        for field in allowed_fields:
            if field in fields:
                sets.append(f"{field} = :{field}")
                params[field] = fields[field]
        
        if len(sets) == 1:  # Only updated_at
            return
        
        query = text(f"""
            UPDATE staging_events
            SET {', '.join(sets)}
            WHERE org_id = :org_id AND id = :id
        """)
        
        with get_session() as session:
            session.execute(query, params)

    def delete(self, org_id: int, staging_id: int) -> None:
        """Delete a single staging event."""
        query = text("""
            DELETE FROM staging_events
            WHERE org_id = :org_id AND id = :id
        """)
        
        with get_session() as session:
            session.execute(query, {"org_id": org_id, "id": staging_id})

    def create(self, org_id: int, event_data: dict) -> int:
        """Create a new staging event and return its ID."""
        query = text("""
            INSERT INTO staging_events (
                org_id, row_index, date, show_time, name, load_in,
                event_series, producer_name, producer_phone, notes,
                is_valid, errors_json, warnings_json, created_at, updated_at
            )
            VALUES (
                :org_id, :row_index, :date, :show_time, :name, :load_in,
                :event_series, :producer_name, :producer_phone, :notes,
                :is_valid, :errors_json, :warnings_json, :now, :now
            )
            RETURNING id
        """)
        
        now = now_utc()
        
        with get_session() as session:
            result = session.execute(query, {
                "org_id": org_id,
                "row_index": event_data.get("row_index", 0),
                "date": event_data.get("date"),
                "show_time": event_data.get("show_time"),
                "name": event_data.get("name"),
                "load_in": event_data.get("load_in"),
                "event_series": event_data.get("event_series"),
                "producer_name": event_data.get("producer_name"),
                "producer_phone": event_data.get("producer_phone"),
                "notes": event_data.get("notes"),
                "is_valid": event_data.get("is_valid", False),
                "errors_json": json.dumps(event_data.get("errors", []), ensure_ascii=False),
                "warnings_json": json.dumps(event_data.get("warnings", []), ensure_ascii=False),
                "now": now,
            })
            return result.scalar_one()

    def count_valid(self, org_id: int) -> int:
        """Count valid staging events."""
        query = text("""
            SELECT COUNT(*) FROM staging_events
            WHERE org_id = :org_id AND is_valid = TRUE
        """)
        
        with get_session() as session:
            return session.execute(query, {"org_id": org_id}).scalar_one()

    def count_total(self, org_id: int) -> int:
        """Count all staging events."""
        query = text("""
            SELECT COUNT(*) FROM staging_events
            WHERE org_id = :org_id
        """)
        
        with get_session() as session:
            return session.execute(query, {"org_id": org_id}).scalar_one()


class ImportJobRepository:
    """Repository for import_jobs table"""

    def create_job(
        self,
        org_id: int,
        job_type: str,
        source: str,
        status: str = "running",
    ) -> int:
        """Create a new import job and return its ID."""
        query = text("""
            INSERT INTO import_jobs (
                org_id, job_type, source, status, started_at
            )
            VALUES (
                :org_id, :job_type, :source, :status, :now
            )
            RETURNING job_id
        """)
        
        with get_session() as session:
            result = session.execute(query, {
                "org_id": org_id,
                "job_type": job_type,
                "source": source,
                "status": status,
                "now": now_utc(),
            })
            return result.scalar_one()

    def update_job(
        self,
        job_id: int,
        status: str,
        details: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update an import job status and details."""
        query = text("""
            UPDATE import_jobs
            SET status = :status,
                finished_at = :now,
                details = :details,
                error_message = :error_message
            WHERE job_id = :job_id
        """)
        
        with get_session() as session:
            session.execute(query, {
                "job_id": job_id,
                "status": status,
                "details": json.dumps(details, ensure_ascii=False) if details else None,
                "error_message": error_message,
                "now": now_utc(),
            })

    def get_latest_job(self, org_id: int, job_type: str) -> Optional[dict]:
        """Get the most recent import job."""
        query = text("""
            SELECT *
            FROM import_jobs
            WHERE org_id = :org_id AND job_type = :job_type
            ORDER BY started_at DESC
            LIMIT 1
        """)
        
        with get_session() as session:
            result = session.execute(query, {"org_id": org_id, "job_type": job_type})
            row = result.mappings().first()
            return dict(row) if row else None
