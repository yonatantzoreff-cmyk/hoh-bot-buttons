"""Core service layer for HOH bot."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from app import twilio_client
from app.credentials import (
    CONTENT_SID_CONFIRM,
    CONTENT_SID_CONTACT,
    CONTENT_SID_HALVES,
    CONTENT_SID_INIT,
    CONTENT_SID_NOT_SURE,
    CONTENT_SID_RANGES,
)
from app.repositories import (
    ContactRepository,
    ConversationRepository,
    EmployeeRepository,
    EmployeeShiftRepository,
    EventRepository,
    MessageRepository,
    OrgRepository,
    TemplateRepository,
)
from app.utils.actions import ParsedAction, parse_action_id
from app.utils.phone import normalize_phone_to_e164_il

logger = logging.getLogger(__name__)

# TODO: tie this to the org's timezone once multi-org support is implemented.
LOCAL_TZ = timezone(timedelta(hours=2))

RANGE_BOUNDS: Dict[int, tuple[int, int]] = {
    1: (0, 4),
    2: (4, 8),
    3: (8, 12),
    4: (12, 16),
    5: (16, 20),
    6: (20, 24),
}


def _range_labels() -> List[str]:
    labels: List[str] = []
    for idx in range(1, 7):
        start, end = RANGE_BOUNDS[idx]
        labels.append(f"{start:02d}:00–{end:02d}:00")
    return labels


def _half_hour_slots_for_range(range_id: int) -> List[str]:
    if range_id not in RANGE_BOUNDS:
        raise ValueError(f"Unknown range id {range_id}")

    start_hour, _ = RANGE_BOUNDS[range_id]
    start_dt = datetime(2000, 1, 1, start_hour, 0)
    return [
        (start_dt + timedelta(minutes=30 * i)).strftime("%H:%M")
        for i in range(8)
    ]


class HOHService:
    def __init__(self):
        self.orgs = OrgRepository()
        self.events = EventRepository()
        self.contacts = ContactRepository()
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
        self.templates = TemplateRepository()
        self.employees = EmployeeRepository()
        self.employee_shifts = EmployeeShiftRepository()

    # --- EMPLOYEES ---

    def create_employee(
        self,
        org_id: int,
        name: str,
        phone: str,
        role: Optional[str] = None,
        notes: Optional[str] = None,
        is_active: bool = True,
    ) -> dict:
        """
        יצירת עובד חדש במערכת.
        מחזיר את רשומת העובד כ-dict.
        """
        employee_id = self.employees.create_employee(
            org_id=org_id,
            name=name,
            phone=phone,
            role=role,
            notes=notes,
            is_active=is_active,
        )
        employee = self.employees.get_employee_by_id(
            org_id=org_id,
            employee_id=employee_id,
        )
        return employee

    def get_or_create_employee_by_phone(
        self,
        org_id: int,
        name: str,
        phone: str,
        role: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        מחפש עובד לפי טלפון.
        אם לא קיים – יוצר אחד חדש.
        """
        existing = self.employees.get_employee_by_phone(
            org_id=org_id,
            phone=phone,
        )
        if existing:
            return existing

        return self.create_employee(
            org_id=org_id,
            name=name,
            phone=phone,
            role=role,
            notes=notes,
            is_active=True,
        )

    # --- EMPLOYEE SHIFTS ---

    def assign_employee_to_event(
        self,
        org_id: int,
        event_id: int,
        employee_id: int,
        call_time: datetime,
        shift_role: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        משייך עובד לאירוע מסוים עם שעת כניסה (call_time) ותפקיד.
        מחזיר את רשומת המשמרת שנוצרה.
        """
        shift_id = self.employee_shifts.create_shift(
            org_id=org_id,
            event_id=event_id,
            employee_id=employee_id,
            call_time=call_time,
            shift_role=shift_role,
            notes=notes,
        )

        # שולף שוב את המשמרת עם ה-join לעובד
        shifts = self.employee_shifts.list_shifts_for_event(
            org_id=org_id,
            event_id=event_id,
        )
        for s in shifts:
            if s["shift_id"] == shift_id:
                return s

        # fallback – אם מסיבה כלשהי לא מצאנו
        return {"shift_id": shift_id}

    def list_event_employees(self, org_id: int, event_id: int):
        """
        מחזיר את רשימת המשמרות באירוע כולל פרטי העובדים.
        """
        return self.employee_shifts.list_shifts_for_event(
            org_id=org_id,
            event_id=event_id,
        )

    def list_employees(self, org_id: int, active_only: bool = True):
        """
        מחזיר רשימת עובדים.
        """
        return self.employees.list_employees(org_id=org_id, active_only=active_only)

    def get_employee(self, org_id: int, employee_id: int):
        """
        מחזיר עובד בודד.
        """
        return self.employees.get_employee_by_id(org_id=org_id, employee_id=employee_id)

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
        """
        עדכון עובד.
        """
        self.employees.update_employee(
            org_id=org_id,
            employee_id=employee_id,
            name=name,
            phone=phone,
            role=role,
            notes=notes,
        )

    def soft_delete_employee(self, org_id: int, employee_id: int):
        """
        מחיקה רכה של עובד (is_active=false).
        """
        self.employees.soft_delete_employee(org_id=org_id, employee_id=employee_id)

    def get_shift(self, org_id: int, shift_id: int):
        """
        מחזיר משמרת בודדת.
        """
        return self.employee_shifts.get_shift_by_id(org_id=org_id, shift_id=shift_id)

    def update_shift(
        self,
        org_id: int,
        shift_id: int,
        *,
        call_time=None,
        shift_role: Optional[str] = None,
        notes: Optional[str] = None,
    ):
        """
        עדכון משמרת.
        """
        self.employee_shifts.update_shift(
            org_id=org_id,
            shift_id=shift_id,
            call_time=call_time,
            shift_role=shift_role,
            notes=notes,
        )

    def delete_shift(self, org_id: int, shift_id: int):
        """
        מחיקה של משמרת.
        """
        self.employee_shifts.delete_shift(org_id=org_id, shift_id=shift_id)

    # region Event + contact bootstrap -------------------------------------------------
    def create_event_with_producer_conversation(
        self,
        org_id: int,
        hall_id: int,
        event_name: str,
        event_date_str: str,
        show_time_str: str,
        producer_name: str,
        producer_phone: str,
    ) -> dict:
        event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
        show_time = self._combine_time(event_date, show_time_str)

        normalized_phone = normalize_phone_to_e164_il(producer_phone)

        producer_contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id,
            phone=normalized_phone,
            name=producer_name,
            role="producer",
        )

        event_id = self.events.create_event(
            org_id=org_id,
            hall_id=hall_id,
            name=event_name,
            event_date=event_date,
            show_time=show_time,
            status="pending",
            producer_contact_id=producer_contact_id,
        )

        conv_id = self.conversations.create_conversation(
            org_id=org_id,
            event_id=event_id,
            contact_id=producer_contact_id,
            channel="whatsapp",
            status="open",
        )

        return {
            "event_id": event_id,
            "contact_id": producer_contact_id,
            "conversation_id": conv_id,
        }

    @staticmethod
    def _get_contact_value(contact: Any, field: str) -> Any:
        if hasattr(contact, field):
            return getattr(contact, field)

        if isinstance(contact, dict):
            return contact.get(field)

        try:
            return contact.get(field)
        except AttributeError:
            try:
                return contact[field]
            except Exception:
                return None

    def list_events_for_org(self, org_id: int):
        events = self.events.list_events_for_org(org_id)
        latest_status_by_event = self.messages.get_latest_status_by_event(org_id)

        enriched_events = []
        for event in events:
            event_dict = dict(event)
            event_id = event_dict.get("event_id")

            producer_contact_id = event_dict.get("producer_contact_id")
            producer_name = event_dict.get("producer_name")
            producer_phone = event_dict.get("producer_phone")

            if producer_contact_id and (producer_name is None or producer_phone is None):
                producer_contact = self.contacts.get_contact_by_id(
                    org_id=org_id, contact_id=producer_contact_id
                )
                event_dict["producer_name"] = producer_name or self._get_contact_value(
                    producer_contact, "name"
                )
                event_dict["producer_phone"] = producer_phone or self._get_contact_value(
                    producer_contact, "phone"
                )
            else:
                event_dict["producer_name"] = producer_name
                event_dict["producer_phone"] = producer_phone

            technical_contact_id = event_dict.get("technical_contact_id")
            technical_phone = event_dict.get("technical_phone")

            if technical_contact_id and technical_phone is None:
                technical_contact = self.contacts.get_contact_by_id(
                    org_id=org_id, contact_id=technical_contact_id
                )
                event_dict["technical_phone"] = technical_phone or self._get_contact_value(
                    technical_contact, "phone"
                )
            else:
                event_dict["technical_phone"] = technical_phone

            if event_id:
                event_dict["init_sent_at"] = self.messages.get_last_sent_at_for_content(
                    org_id=org_id,
                    event_id=event_id,
                    content_sid=CONTENT_SID_INIT,
                )
                event_dict["latest_delivery_status"] = latest_status_by_event.get(event_id)
            else:
                event_dict["latest_delivery_status"] = None

            enriched_events.append(event_dict)

        return enriched_events

    def list_contacts_by_role(self, org_id: int) -> dict[str, list[dict]]:
        contacts = self.contacts.list_contacts(org_id=org_id)

        grouped: dict[str, list[dict]] = {"producer": [], "technical": []}
        for contact in contacts:
            role = contact.get("role") or "producer"
            grouped.setdefault(role, []).append(dict(contact))

        return grouped

    def get_contact(self, org_id: int, contact_id: int):
        return self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)

    def create_contact(self, org_id: int, name: str, phone: str, role: str) -> int:
        role_value = role if role in {"producer", "technical"} else "producer"
        normalized_phone = normalize_phone_to_e164_il(phone)
        contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id, phone=normalized_phone, name=name, role=role_value
        )
        self.contacts.update_contact(
            org_id=org_id,
            contact_id=contact_id,
            name=name,
            phone=normalized_phone,
            role=role_value,
        )
        return contact_id

    def update_contact(
        self,
        org_id: int,
        contact_id: int,
        *,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
    ) -> None:
        normalized_phone = normalize_phone_to_e164_il(phone) if phone else None
        role_value = role if role in {None, "producer", "technical"} else None
        self.contacts.update_contact(
            org_id=org_id,
            contact_id=contact_id,
            name=name,
            phone=normalized_phone,
            role=role_value,
        )

    def delete_contact(self, org_id: int, contact_id: int) -> None:
        related_events = self.events.count_events_for_contact(
            org_id=org_id, contact_id=contact_id
        )
        if related_events:
            raise ValueError(
                "Cannot delete contact while it is linked to existing events."
            )

        self.events.clear_contact_references(org_id=org_id, contact_id=contact_id)
        self.messages.clear_contact(org_id=org_id, contact_id=contact_id)
        self.conversations.clear_contact(org_id=org_id, contact_id=contact_id)
        self.contacts.delete_contact(org_id=org_id, contact_id=contact_id)

    def get_event_with_contacts(self, org_id: int, event_id: int):
        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        if not event:
            return None

        event_dict = dict(event)

        producer_contact_id = event_dict.get("producer_contact_id")
        if producer_contact_id:
            producer_contact = self.contacts.get_contact_by_id(
                org_id=org_id, contact_id=producer_contact_id
            )
            if producer_contact:
                event_dict["producer_name"] = self._get_contact_value(
                    producer_contact, "name"
                )
                event_dict["producer_phone"] = self._get_contact_value(
                    producer_contact, "phone"
                )

        technical_contact_id = event_dict.get("technical_contact_id")
        if technical_contact_id:
            technical_contact = self.contacts.get_contact_by_id(
                org_id=org_id, contact_id=technical_contact_id
            )
            if technical_contact:
                event_dict["technical_name"] = self._get_contact_value(
                    technical_contact, "name"
                )
                event_dict["technical_phone"] = self._get_contact_value(
                    technical_contact, "phone"
                )

        return event_dict

    def update_event_with_contacts(
        self,
        *,
        org_id: int,
        event_id: int,
        event_name: str,
        event_date_str: str,
        show_time_str: Optional[str],
        load_in_time_str: Optional[str],
        producer_name: Optional[str],
        producer_phone: Optional[str],
        technical_name: Optional[str],
        technical_phone: Optional[str],
        notes: Optional[str] = None,
    ) -> None:
        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        if not event:
            raise ValueError("Event not found")

        event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
        show_time = self._combine_time(event_date, show_time_str)
        load_in_time = self._combine_time(event_date, load_in_time_str)

        producer_contact_id = event.get("producer_contact_id")
        if producer_phone or producer_name:
            if producer_contact_id:
                self.contacts.update_contact(
                    org_id=org_id,
                    contact_id=producer_contact_id,
                    name=producer_name if producer_name else None,
                    phone=producer_phone if producer_phone else None,
                    role="producer",
                )
            elif producer_phone:
                producer_contact_id = self.contacts.get_or_create_by_phone(
                    org_id=org_id,
                    phone=producer_phone,
                    name=producer_name or producer_phone,
                    role="producer",
                )

        technical_contact_id = event.get("technical_contact_id")
        if technical_phone or technical_name:
            if technical_contact_id:
                self.contacts.update_contact(
                    org_id=org_id,
                    contact_id=technical_contact_id,
                    name=technical_name if technical_name else None,
                    phone=technical_phone if technical_phone else None,
                    role="technical",
                )
            elif technical_phone:
                technical_contact_id = self.contacts.get_or_create_by_phone(
                    org_id=org_id,
                    phone=technical_phone,
                    name=technical_name or technical_phone,
                    role="technical",
                )

        self.events.update_event(
            org_id=org_id,
            event_id=event_id,
            name=event_name,
            event_date=event_date,
            show_time=show_time,
            load_in_time=load_in_time,
            producer_contact_id=producer_contact_id,
            technical_contact_id=technical_contact_id,
            notes=notes,
        )

    @staticmethod
    def _combine_time(event_date: date, time_str: Optional[str]):
        if not time_str:
            return None

        time_part = datetime.strptime(time_str, "%H:%M").time()
        return datetime.combine(event_date, time_part)

    def delete_event(self, org_id: int, event_id: int) -> None:
        self.conversations.clear_last_message_for_event(org_id=org_id, event_id=event_id)
        self.conversations.delete_by_event(org_id=org_id, event_id=event_id)
        self.events.delete_event(org_id=org_id, event_id=event_id)

    # endregion -----------------------------------------------------------------------

    def list_messages_with_events(self, org_id: int) -> list[dict]:
        return self.messages.list_messages_with_events(org_id)

    async def send_init_for_event(
        self, event_id: int, org_id: int = 1, contact_id: Optional[int] = None
    ) -> None:
        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        if not event:
            raise ValueError("Event not found")

        org = self.orgs.get_org_by_id(org_id)
        if not org:
            raise ValueError("Org not found")

        producer_contact_id = contact_id or event.get("producer_contact_id")
        if not producer_contact_id:
            raise ValueError("Event missing producer_contact_id; cannot send INIT")

        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=producer_contact_id)
        if not contact:
            raise ValueError("Producer contact not found")

        original_phone = self._get_contact_value(contact, "phone")
        normalized_phone = normalize_phone_to_e164_il(original_phone)
        if not normalized_phone:
            raise ValueError("Valid phone number is missing")

        if normalized_phone != original_phone:
            self.contacts.update_contact_phone(
                org_id=org_id, contact_id=producer_contact_id, phone=normalized_phone
            )

        conversation_id = self._ensure_conversation(org_id, event_id, producer_contact_id)

        event_date = event.get("event_date")
        show_time = event.get("show_time")

        event_date_str = event_date.strftime("%d.%m.%Y") if event_date else ""
        show_time_str = show_time.strftime("%H:%M") if show_time else ""

        init_vars = {
            "1": self._get_contact_value(contact, "name") or "Producer",
            "2": event.get("name") or "",
            "3": event_date_str,
            "4": show_time_str,
            "5": str(event_id),
            "6": org.get("name") or "",
        }

        twilio_response = twilio_client.send_content_message(
            to=normalized_phone,
            content_sid=CONTENT_SID_INIT,
            content_variables=init_vars,
        )

        whatsapp_sid = getattr(twilio_response, "sid", None)
        raw_payload = {
            "content_sid": CONTENT_SID_INIT,
            "variables": init_vars,
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=producer_contact_id,
            direction="outgoing",
            body=f"INIT sent for event {event_id}",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )

    async def send_ranges_for_event(self, org_id: int, event_id: int, contact_id: int) -> None:
        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        if not contact:
            raise ValueError("Contact not found")

        conversation_id = self._ensure_conversation(org_id, event_id, contact_id)
        ranges = _range_labels()

        variables = {
            "range1": ranges[0],
            "range2": ranges[1],
            "range3": ranges[2],
            "range4": ranges[3],
            "range5": ranges[4],
            "range6": ranges[5],
            "event_id": str(event_id),
        }

        twilio_resp = twilio_client.send_content_message(
            to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
            content_sid=CONTENT_SID_RANGES,
            content_variables=variables,
        )

        whatsapp_sid = getattr(twilio_resp, "sid", None)
        raw_payload = {
            "content_sid": CONTENT_SID_RANGES,
            "variables": variables,
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body="Sent ranges list",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )

    async def send_halves_for_event_range(
        self,
        org_id: int,
        event_id: int,
        contact_id: int,
        range_id: int,
    ) -> None:
        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        if not contact:
            raise ValueError("Contact not found")

        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )
        conversation_id = conversation.get("conversation_id") if conversation else None
        if not conversation_id:
            conversation_id = self._ensure_conversation(org_id, event_id, contact_id)

        slots = _half_hour_slots_for_range(range_id)
        variables = {
            "h1": slots[0],
            "h2": slots[1],
            "h3": slots[2],
            "h4": slots[3],
            "h5": slots[4],
            "h6": slots[5],
            "h7": slots[6],
            "h8": slots[7],
            "event_id": str(event_id),
            "range_id": str(range_id),
        }

        twilio_resp = twilio_client.send_content_message(
            to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
            content_sid=CONTENT_SID_HALVES,
            content_variables=variables,
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None)

        pending_fields = (conversation or {}).get("pending_data_fields") or {}
        pending_fields.update({"last_range_id": range_id, "last_slots": slots})
        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields=pending_fields,
        )

        raw_payload = {
            "content_sid": CONTENT_SID_HALVES,
            "variables": variables,
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body=f"Sent halves for range {range_id}",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )

    async def send_confirm_for_slot(
        self,
        org_id: int,
        event_id: int,
        contact_id: int,
        slot_label: str,
    ) -> None:
        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        org = self.orgs.get_org_by_id(org_id)
        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)

        if not (event and org and contact):
            raise ValueError("Missing entities for confirm")

        conversation_id = self._ensure_conversation(org_id, event_id, contact_id)

        event_date = event.get("event_date")
        show_time = event.get("show_time")

        event_date_str = event_date.strftime("%d.%m.%Y") if event_date else ""
        show_time_str = show_time.strftime("%H:%M") if show_time else ""

        variables = {
            "event_name": event.get("name") or "",
            "event_date": event_date_str,
            "show_time": show_time_str,
            "slot": slot_label,
            "event_id": str(event_id),
        }

        twilio_resp = twilio_client.send_content_message(
            to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
            content_sid=CONTENT_SID_CONFIRM,
            content_variables=variables,
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None)

        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )
        pending_fields = (conversation or {}).get("pending_data_fields") or {}
        pending_fields.update({"last_slot_label": slot_label})
        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields=pending_fields,
        )

        raw_payload = {
            "content_sid": CONTENT_SID_CONFIRM,
            "variables": variables,
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body=f"Sent confirm for slot {slot_label}",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )

    async def run_due_followups(self, org_id: int = 1) -> int:
        now = datetime.now(timezone.utc)
        due_followups = self.messages.find_due_followups(org_id=org_id, now=now)
        processed = 0

        for item in due_followups:
            contact = self.contacts.get_contact_by_id(
                org_id=org_id, contact_id=item.get("contact_id")
            )
            event = self.events.get_event_by_id(org_id=org_id, event_id=item.get("event_id"))
            template = self.templates.get_template_by_id(
                org_id=org_id, template_id=item.get("next_template_id")
            )

            if not contact or not event or not template:
                continue

            content_sid = template.get("content_sid")
            if not content_sid:
                continue

            variables = self._build_followup_variables(contact=contact, event=event)

            to_phone = normalize_phone_to_e164_il(self._get_contact_value(contact, "phone"))

            twilio_response = twilio_client.send_content_message(
                to=to_phone,
                content_sid=content_sid,
                content_variables=variables,
                channel=template.get("channel", "whatsapp"),
            )

            whatsapp_sid = getattr(twilio_response, "sid", None)
            body = f"Followup sent via template {template.get('name') or template.get('template_id')}"
            raw_payload = {
                "content_sid": content_sid,
                "variables": variables,
                "followup_rule_id": item.get("rule_id"),
                "twilio_message_sid": whatsapp_sid,
            }

            self.messages.log_message(
                org_id=org_id,
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

            processed += 1

        return processed

    def _build_followup_variables(self, contact: dict, event: dict) -> dict:
        event_date = event.get("event_date")
        show_time = event.get("show_time")

        event_date_str = event_date.strftime("%d.%m.%Y") if event_date else ""
        show_time_str = show_time.strftime("%H:%M") if show_time else ""

        return {
            "producer_name": self._get_contact_value(contact, "name") or "Producer",
            "event_name": event.get("name") or "",
            "event_date": event_date_str,
            "show_time": show_time_str,
        }

    async def handle_whatsapp_webhook(self, payload: dict, org_id: int = 1) -> None:
        def _looks_like_action_id(value: str) -> bool:
            prefixes = (
                "CHOOSE_TIME_EVT_",
                "RANGE_",
                "HALF_",
                "BACK_TO_",
                "CONFIRM_SLOT_EVT_",
                "CHANGE_SLOT_EVT_",
                "NOT_SURE_EVT_",
                "NOT_CONTACT_EVT_",
            )
            return any(value.startswith(prefix) for prefix in prefixes)

        def _pick_interactive_value(data: Dict[str, Any]) -> str:
            candidates = [
                data.get("ButtonPayload"),
                data.get("ListResponse[Selection][Id]"),
                data.get("ListResponse.SelectionId"),
                data.get("ListItemValue"),
                data.get("ListResponse[Selection][Title]"),
                data.get("ListResponse.SelectionTitle"),
                data.get("ButtonText"),
                data.get("ListItemTitle"),
            ]

            for value in candidates:
                if value:
                    return str(value).strip()

            return ""

        interactive_value = _pick_interactive_value(payload)

        from_number = (payload.get("From") or payload.get("WaId") or "").strip()
        normalized_from = normalize_phone_to_e164_il(from_number)
        message_body = (payload.get("Body") or "").strip()
        if not message_body:
            contact_summary = self._contact_summary_from_payload(payload)
            if contact_summary:
                message_body = contact_summary

        logger.info("Incoming WhatsApp body: %s", message_body)

        action_id = ""
        if message_body and _looks_like_action_id(message_body):
            action_id = message_body
        elif interactive_value and _looks_like_action_id(interactive_value):
            action_id = interactive_value
        else:
            action_id = interactive_value or ""

        parsed_action: Optional[ParsedAction] = parse_action_id(action_id) if action_id else None
        logger.info("Parsed action: %s", parsed_action)

        contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id,
            phone=normalized_from,
            name=payload.get("ProfileName") or normalized_from,
            role="producer",
        )

        event_id = parsed_action.get("event_id") if parsed_action else None
        conversation = None
        event = None

        if interactive_value and not event_id:
            logger.warning("Interactive payload missing event id", extra={"payload": payload})
            return

        if event_id:
            event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
            if event:
                conversation = self.conversations.get_open_conversation(
                    org_id=org_id, event_id=event_id, contact_id=contact_id
                )
                if not conversation:
                    conv_id = self.conversations.create_conversation(
                        org_id=org_id,
                        event_id=event_id,
                        contact_id=contact_id,
                        channel="whatsapp",
                        status="open",
                    )
                    conversation = {"conversation_id": conv_id, "event_id": event_id}

        if not event_id:
            conversation = self.conversations.get_recent_open_for_contact(
                org_id=org_id, contact_id=contact_id
            )
            if conversation:
                event_id = conversation.get("event_id")
                if event_id:
                    event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)

        if not conversation or not event_id or not event:
            return

        conversation_id = conversation.get("conversation_id")

        received_at = datetime.now(timezone.utc)
        body_text = message_body or interactive_value
        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="incoming",
            body=body_text,
            raw_payload=payload,
            received_at=received_at,
        )

        if not parsed_action:
            await self._handle_contact_followup(
                body_text=message_body,
                payload=payload,
                event_id=event_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                org_id=org_id,
            )
            return

        action_type = parsed_action.get("type")

        if action_type == "CHOOSE_TIME":
            await self.send_ranges_for_event(org_id, event_id, contact_id)
            return

        if action_type == "RANGE":
            await self.send_halves_for_event_range(
                org_id=org_id,
                event_id=event_id,
                contact_id=contact_id,
                range_id=parsed_action.get("range_id") or 1,
            )
            return

        if action_type == "HALF":
            range_id = parsed_action.get("range_id") or 1
            half_index = parsed_action.get("half_index") or 1
            slots = _half_hour_slots_for_range(range_id)
            slot_label = slots[half_index - 1] if 0 < half_index <= len(slots) else slots[0]

            conversation = self.conversations.get_open_conversation(
                org_id=org_id, event_id=event_id, contact_id=contact_id
            )
            pending_fields = (conversation or {}).get("pending_data_fields") or {}
            pending_fields.update(
                {"last_range_id": range_id, "last_slots": slots, "last_slot_label": slot_label}
            )
            self.conversations.update_pending_data_fields(
                org_id=org_id,
                conversation_id=conversation_id,
                pending_data_fields=pending_fields,
            )

            await self.send_confirm_for_slot(
                org_id=org_id,
                event_id=event_id,
                contact_id=contact_id,
                slot_label=slot_label,
            )
            return

        if action_type == "BACK_TO_RANGES":
            await self.send_ranges_for_event(org_id, event_id, contact_id)
            return

        if action_type == "BACK_TO_INIT":
            await self.send_init_for_event(event_id=event_id, org_id=org_id)
            return

        if action_type == "CONFIRM_SLOT":
            await self._apply_confirmed_slot(
                event_id=event_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
                org_id=org_id,
            )
            return

        if action_type == "CHANGE_SLOT":
            conversation = self.conversations.get_open_conversation(
                org_id=org_id, event_id=event_id, contact_id=contact_id
            )
            pending = (conversation or {}).get("pending_data_fields") or {}
            last_range_id = pending.get("last_range_id") or 1
            await self.send_halves_for_event_range(
                org_id=org_id,
                event_id=event_id,
                contact_id=contact_id,
                range_id=last_range_id,
            )
            return

        if action_type == "NOT_SURE":
            await self._handle_not_sure(
                event_id=event_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                org_id=org_id,
            )
            return

        if action_type == "NOT_CONTACT":
            await self._handle_not_contact(
                event_id=event_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                org_id=org_id,
            )
            return

    @staticmethod
    def _parse_contact_from_text(text: str) -> tuple[str, str]:
        """Try to pull a phone/name combination from free text (CSV, lines, etc)."""

        text = (text or "").replace("\n", " ").strip()
        if not text:
            return "", ""

        parts = [part.strip() for part in re.split(r"[;,]", text) if part.strip()]

        phone_candidate = ""
        name_candidate = ""

        for part in parts:
            if not phone_candidate and re.search(r"\d", part):
                phone_candidate = part
            elif not name_candidate:
                name_candidate = part

        if not phone_candidate:
            match = re.search(r"[+]?\d[\d\s()\-]{5,}", text)
            if match:
                phone_candidate = match.group(0)

        if not name_candidate:
            stripped_text = re.sub(r"[+]?\d[\d\s()\-]{5,}", "", text).strip()
            if stripped_text:
                name_candidate = stripped_text.split()[0]

        return phone_candidate, name_candidate

    @staticmethod
    def _extract_contact_details(payload: dict, body_text: str) -> tuple[str, str]:
        payload = payload or {}

        def _first_non_empty(keys: tuple[str, ...]) -> str:
            for key in keys:
                value = payload.get(key)
                if value:
                    return str(value).strip()
            return ""

        vcard_phone, vcard_name = HOHService._extract_contact_from_vcard_media(payload)

        payload_phone = vcard_phone or _first_non_empty(
            (
                "Contacts[0][PhoneNumber]",
                "Contacts[0][WaId]",
            )
        )
        payload_name = vcard_name or _first_non_empty(
            (
                "Contacts[0][Name]",
                "Contacts[0][FirstName]",
                "Contacts[0][WaId]",
            )
        )

        fallback_text = body_text or ""
        text_phone, text_name = HOHService._parse_contact_from_text(body_text)
        if not payload_name and not vcard_name and fallback_text.strip():
            text_name = fallback_text.strip()

        phone_candidate = payload_phone or text_phone
        if phone_candidate and any(ch.isalpha() for ch in phone_candidate):
            match = re.search(r"[+]?\d[\d\s()\-]{5,}", phone_candidate)
            if match:
                phone_candidate = match.group(0)
        if not phone_candidate:
            digits = [token for token in fallback_text.split() if token]
            phone_candidate = next(
                (d for d in digits if any(ch.isdigit() for ch in d)), fallback_text
            )

        phone = normalize_phone_to_e164_il(phone_candidate)
        name = payload_name or text_name or fallback_text.strip() or phone

        return phone, name

    @staticmethod
    def _extract_contact_from_vcard_media(payload: dict) -> Tuple[str, str]:
        """Try to parse a shared contact from vCard media items."""

        try:
            num_media = int(payload.get("NumMedia") or payload.get("numMedia") or 0)
        except (TypeError, ValueError):
            num_media = 0

        if num_media <= 0:
            return "", ""

        def _media_value(idx: int, key: str) -> str:
            return (
                payload.get(f"{key}{idx}")
                or payload.get(f"{key.lower()}{idx}")
                or ""
            )

        for idx in range(num_media):
            url = _media_value(idx, "MediaUrl")
            content_type = _media_value(idx, "MediaContentType")
            filename = _media_value(idx, "MediaFilename")

            if not url:
                continue

            looks_like_vcard = False
            if content_type and "vcard" in content_type.lower():
                looks_like_vcard = True
            if filename and filename.lower().endswith(".vcf"):
                looks_like_vcard = True

            if not looks_like_vcard:
                continue

            vcard_text = HOHService._download_media_text(url)
            if not vcard_text:
                continue

            phone, name = HOHService._parse_vcard_contact(vcard_text)
            if phone or name:
                return phone, name

        return "", ""

    @staticmethod
    def _download_media_text(url: str) -> str:
        """Download Twilio-hosted media using account credentials."""

        try:
            response = requests.get(
                url,
                auth=(twilio_client.ACCOUNT_SID, twilio_client.AUTH_TOKEN),
                timeout=10,
            )
            if response.ok:
                if response.content:
                    return response.content.decode("utf-8", errors="replace")
                return response.text
            logger.warning(
                "Failed to download media", extra={"url": url, "status": response.status_code}
            )
        except Exception as exc:  # pragma: no cover - network/requests safety
            logger.warning("Error downloading media", exc_info=exc, extra={"url": url})

        return ""

    @staticmethod
    def _parse_vcard_contact(vcard_text: str) -> Tuple[str, str]:
        """Extract phone and name from a minimal vCard payload."""

        phone = ""
        name = ""

        for raw_line in vcard_text.splitlines():
            line = raw_line.strip()
            upper_line = line.upper()

            if not name:
                if upper_line.startswith("FN:"):
                    name = line.split(":", 1)[1].strip()
                elif upper_line.startswith("N:"):
                    name_parts = line.split(":", 1)[1].split(";")
                    name = " ".join(part for part in name_parts if part).strip()

            if not phone and "TEL" in upper_line:
                phone = line.split(":", 1)[-1].strip()

            if phone and name:
                break

        return phone, name

    @staticmethod
    def _contact_summary_from_payload(payload: dict) -> str:
        """Return a human-friendly description of a shared contact payload."""

        phone, name = HOHService._extract_contact_details(payload, "")
        if phone or name:
            if phone and name:
                return f"Contact shared: {name} ({phone})"
            return f"Contact shared: {name or phone}"

        return ""

    async def _handle_contact_followup(
        self,
        body_text: str,
        payload: dict,
        event_id: int,
        contact_id: int,
        conversation_id: int,
        org_id: int,
    ) -> None:
        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )
        pending = (conversation or {}).get("pending_data_fields") or {}

        if not pending.get("awaiting_new_contact"):
            return

        phone, name = self._extract_contact_details(payload, body_text)

        if not phone:
            logger.warning(
                "Missing phone number in NOT CONTACT follow-up",
                extra={"event_id": event_id, "contact_id": contact_id, "payload": payload},
            )
            return

        new_contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id,
            phone=phone,
            name=name,
            role="technical",
        )

        self.events.update_event_fields(
            org_id=org_id, event_id=event_id, technical_contact_id=new_contact_id
        )
        self.events.update_event_fields(
            org_id=org_id, event_id=event_id, status="pending"
        )

        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        if contact:
            thanks_body = "תודה!"
            twilio_resp = twilio_client.send_text(
                to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
                body=thanks_body,
            )
            whatsapp_sid = getattr(twilio_resp, "sid", None) if twilio_resp else None

            raw_payload = {
                "type": "contact_acknowledgment",
                "body": thanks_body,
                "twilio_message_sid": whatsapp_sid,
            }
            self.messages.log_message(
                org_id=org_id,
                conversation_id=conversation_id,
                event_id=event_id,
                contact_id=contact_id,
                direction="outgoing",
                body=thanks_body,
                whatsapp_msg_sid=whatsapp_sid,
                raw_payload=raw_payload,
            )

        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields={},
        )

        await self.send_init_for_event(
            event_id=event_id, org_id=org_id, contact_id=new_contact_id
        )

    async def _handle_not_sure(
        self,
        event_id: int,
        contact_id: int,
        conversation_id: int,
        org_id: int,
    ) -> None:
        followup_at = datetime.now(timezone.utc) + timedelta(hours=72)
        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )
        pending_fields = (conversation or {}).get("pending_data_fields") or {}
        pending_fields.update({"followup_due_at": followup_at.isoformat()})
        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields=pending_fields,
        )

        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        if not contact:
            return

        twilio_resp = twilio_client.send_content_message(
            to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
            content_sid=CONTENT_SID_NOT_SURE,
            content_variables={},
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None)

        raw_payload = {
            "content_sid": CONTENT_SID_NOT_SURE,
            "variables": {},
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body="Sent NOT SURE message",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )

    async def _handle_not_contact(
        self,
        event_id: int,
        contact_id: int,
        conversation_id: int,
        org_id: int,
    ) -> None:
        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        if not contact:
            return

        self.events.update_event_fields(
            org_id=org_id, event_id=event_id, status="contact_required"
        )

        twilio_resp = twilio_client.send_content_message(
            to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
            content_sid=CONTENT_SID_CONTACT,
            content_variables={},
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None)

        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )
        pending = (conversation or {}).get("pending_data_fields") or {}
        pending.update({"awaiting_new_contact": True})
        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields=pending,
        )

        raw_payload = {
            "content_sid": CONTENT_SID_CONTACT,
            "variables": {},
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body="Sent NOT CONTACT template",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )

    async def _apply_confirmed_slot(
        self,
        event_id: int,
        conversation_id: int,
        contact_id: int,
        org_id: int,
    ) -> None:
        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )
        pending = (conversation or {}).get("pending_data_fields") or {}
        slot_label = pending.get("last_slot_label")

        if not slot_label:
            return

        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        event_date: Optional[date] = event.get("event_date") if event else None
        if event_date:
            hour, minute = map(int, slot_label.split(":"))
            load_in_dt = datetime.combine(event_date, time(hour=hour, minute=minute))
            self.events.update_event_fields(
                org_id=org_id, event_id=event_id, load_in_time=load_in_dt, status="confirmed"
            )

        pending.pop("last_slot_label", None)
        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields=pending,
        )

        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        if contact:
            thank_you_body = (
                "תודה לך! אשלח את פרטי הטכנאי שיהיה איתכם בסמוך לאירוע. ניפגש!"
            )
            to_phone = normalize_phone_to_e164_il(self._get_contact_value(contact, "phone"))
            if to_phone:
                twilio_resp = twilio_client.send_text(to=to_phone, body=thank_you_body)
                whatsapp_sid = getattr(twilio_resp, "sid", None) if twilio_resp else None

                raw_payload = {
                    "body": thank_you_body,
                    "type": "load_in_confirmation_followup",
                    "twilio_message_sid": whatsapp_sid,
                }

                self.messages.log_message(
                    org_id=org_id,
                    conversation_id=conversation_id,
                    event_id=event_id,
                    contact_id=contact_id,
                    direction="outgoing",
                    body=thank_you_body,
                    whatsapp_msg_sid=whatsapp_sid,
                    raw_payload=raw_payload,
                )

    def _ensure_conversation(self, org_id: int, event_id: int, contact_id: int) -> int:
        conversation = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )
        if conversation:
            return conversation.get("conversation_id")

        return self.conversations.create_conversation(
            org_id=org_id,
            event_id=event_id,
            contact_id=contact_id,
            channel="whatsapp",
            status="open",
        )
