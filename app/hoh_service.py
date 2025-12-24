"""Core service layer for HOH bot."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
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
    CONTENT_SID_SHIFT_REMINDER,
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
    _NO_UPDATE,
)
from app.utils.actions import ParsedAction, parse_action_id
from app.utils.phone import normalize_phone_to_e164_il
from app.time_utils import (
    get_il_tz,
    parse_local_time_to_utc,
    utc_to_local_datetime,
    utc_to_local_time_str,
    ensure_aware,
    now_utc,
    format_datetime_for_display,
)

logger = logging.getLogger(__name__)

# Use centralized timezone utility
ISRAEL_TZ = get_il_tz()

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
        normalized_phone = normalize_phone_to_e164_il(phone) if phone is not None else None
        employee_id = self.employees.create_employee(
            org_id=org_id,
            name=name,
            phone=normalized_phone,
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
        normalized_phone = normalize_phone_to_e164_il(phone)
        existing = self.employees.get_employee_by_phone(
            org_id=org_id,
            phone=normalized_phone,
        )
        if existing:
            return existing

        return self.create_employee(
            org_id=org_id,
            name=name,
            phone=normalized_phone,
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
        normalized_phone = normalize_phone_to_e164_il(phone) if phone is not None else None
        self.employees.update_employee(
            org_id=org_id,
            employee_id=employee_id,
            name=name,
            phone=normalized_phone,
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
        employee_id=_NO_UPDATE,
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
            employee_id=employee_id,
            call_time=call_time,
            shift_role=shift_role,
            notes=notes,
        )

    def delete_shift(self, org_id: int, shift_id: int):
        """
        מחיקה של משמרת.
        """
        self.employee_shifts.delete_shift(org_id=org_id, shift_id=shift_id)

    def send_shift_reminder(self, org_id: int, shift_id: int):
        """Send a shift reminder Content Template and log it for tracking."""

        shift = self.get_shift(org_id=org_id, shift_id=shift_id)
        if not shift:
            raise ValueError("Shift not found")

        event_id = shift.get("event_id")
        if not event_id:
            raise ValueError("Shift missing event_id")

        event = self.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise ValueError("Event not found for shift reminder")

        employee_phone = shift.get("employee_phone") or ""
        normalized_phone = normalize_phone_to_e164_il(employee_phone)
        if not normalized_phone:
            raise ValueError("Employee phone number invalid")

        employee_name = shift.get("employee_name") or ""
        contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id, phone=normalized_phone, name=employee_name, role="employee"
        )

        conversation_id = self._ensure_conversation(
            org_id=org_id, event_id=event_id, contact_id=contact_id
        )

        variables = self.build_shift_reminder_variables(org_id=org_id, shift_id=shift_id)

        logger.info(
            "Sending shift reminder",
            extra={
                "event_id": event_id,
                "shift_id": shift_id,
                "show_time": self._format_time_israel(event.get("show_time")),
                "call_time": self._format_time_israel(shift.get("call_time")),
                "contact_phone_suffix": (variables.get("8") or "")[-3:],
            },
        )

        twilio_resp = twilio_client.send_content_message(
            to=normalized_phone,
            content_sid=CONTENT_SID_SHIFT_REMINDER,
            content_variables=json.dumps(variables, ensure_ascii=False),
        )

        whatsapp_sid = getattr(twilio_resp, "sid", None)
        raw_payload = {
            "content_sid": CONTENT_SID_SHIFT_REMINDER,
            "variables": variables,
            "twilio_message_sid": whatsapp_sid,
            "event_id": event_id,
            "shift_id": shift_id,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body=f"Shift reminder sent for event {event.get('name', '')}",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )

        self.employee_shifts.mark_24h_reminder_sent(shift_id=shift_id)

        return twilio_resp

    def build_shift_reminder_variables(self, org_id: int, shift_id: int) -> dict:
        """
        Build the variables dict for the shift reminder Content Template.

        Keys must be stringified integers ("1", "2", ...), matching Twilio's
        template variable format.
        """

        shift = self.get_shift(org_id=org_id, shift_id=shift_id)
        if not shift:
            raise ValueError(f"Shift {shift_id} not found for org {org_id}")

        event = self.get_event_with_contacts(org_id=org_id, event_id=shift["event_id"])
        if not event:
            raise ValueError(
                f"Event {shift['event_id']} not found for shift {shift_id} in org {org_id}"
            )

        event_date = event.get("event_date")
        event_date_display = event_date.strftime("%d/%m/%Y") if event_date else ""

        show_time_display = self._format_time_israel(event.get("show_time"))

        call_time = shift.get("call_time")
        call_time_display = self._format_time_israel(call_time)

        employee_name = shift.get("employee_name") or ""
        first_name = employee_name.split()[0] if employee_name else ""

        tech_phone = event.get("technical_phone") or os.getenv("TECH_CONTACT_PHONE")
        support_phone = tech_phone or event.get("producer_phone") or ""

        tech_name = event.get("technical_name") or os.getenv("TECH_CONTACT_NAME")
        support_name = tech_name or event.get("producer_name") or ""

        shift_role = shift.get("shift_role") or ""
        shift_notes = shift.get("notes") or ""
        event_notes = event.get("notes") or ""

        notes_parts = []
        if shift_role:
            notes_parts.append(f"תפקיד: {shift_role}")
        if shift_notes:
            notes_parts.append(shift_notes)
        elif event_notes:
            notes_parts.append(event_notes)

        notes_text = "\n".join(notes_parts)

        def _clean(value: Any, *, fallback: str = "—") -> str:
            if value is None:
                return fallback
            if isinstance(value, str):
                stripped = value.strip()
                return stripped if stripped else fallback
            return str(value)

        variables = {
            "1": _clean(first_name),
            "2": _clean(event.get("name")),
            "3": _clean(event_date_display),
            "4": _clean(show_time_display),
            "5": _clean(call_time_display),
            "6": _clean(notes_text, fallback="-"),
            "7": _clean(support_name),
            "8": _clean(support_phone),
        }

        return variables

    def build_tech_reminder_employee_payload(
        self, org_id: int, event_id: int
    ) -> dict:
        """
        Build the payload for tech reminder employee template.
        
        Returns a dict with:
          - to_phone: technical contact phone as "whatsapp:+972..."
          - variables: dict {"1": ..., "2": ..., ..., "7": ...}
          - opening_employee_metadata: dict with employee info
        
        Raises ValueError if:
          - Event not found
          - No technical contact
          - No technical contact phone
          - No shifts assigned OR cannot determine earliest employee
        """
        
        # 1. Fetch event with contacts
        event = self.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise ValueError(f"Event {event_id} not found")
        
        # 2. Validate technical contact
        technical_contact_id = event.get("technical_contact_id")
        if not technical_contact_id:
            raise ValueError("Event has no technical contact assigned")
        
        technical_phone = event.get("technical_phone")
        technical_name = event.get("technical_name") or ""
        
        if not technical_phone or not technical_phone.strip():
            raise ValueError("Technical contact has no phone number")
        
        # Normalize technical phone to E.164
        normalized_tech_phone = normalize_phone_to_e164_il(technical_phone)
        if not normalized_tech_phone:
            raise ValueError("Technical contact phone is invalid")
        
        # Technical phone for `to` must be whatsapp:+972...
        to_phone = f"whatsapp:{normalized_tech_phone}"
        
        # 3. Get event details
        event_name = event.get("name") or ""
        event_date = event.get("event_date")
        event_date_display = event_date.strftime("%d/%m/%Y") if event_date else ""
        
        load_in_time_dt = event.get("load_in_time")
        load_in_time_display = self._format_time_israel(load_in_time_dt) if load_in_time_dt else "—"
        
        show_time_dt = event.get("show_time")
        show_time_display = self._format_time_israel(show_time_dt) if show_time_dt else "—"
        
        # 4. Find opening employee (earliest call_time)
        shifts = self.employee_shifts.list_shifts_for_event(
            org_id=org_id,
            event_id=event_id,
        )
        
        if not shifts:
            raise ValueError("No employees assigned to this event. Cannot send reminder.")
        
        # Find shift with earliest call_time
        opening_shift = None
        earliest_time = None
        
        for shift in shifts:
            call_time = shift.get("call_time")
            if call_time:
                if earliest_time is None or call_time < earliest_time:
                    earliest_time = call_time
                    opening_shift = shift
        
        if not opening_shift:
            raise ValueError("Cannot determine opening employee (no valid call_time in shifts)")
        
        employee_name = opening_shift.get("employee_name") or ""
        employee_phone = opening_shift.get("employee_phone") or ""
        
        # 5. Extract first names
        tech_first_name = technical_name.split()[0] if technical_name.strip() else "טכנאי"
        employee_first_name = employee_name.split()[0] if employee_name.strip() else "עובד"
        
        # 6. Format employee phone to E.164
        if employee_phone:
            normalized_emp_phone = normalize_phone_to_e164_il(employee_phone)
        else:
            normalized_emp_phone = "—"
        
        # 7. Build variables dict (must be "1", "2", ... "7")
        variables = {
            "1": tech_first_name,                # Technical contact first name
            "2": event_name,                      # Event name
            "3": event_date_display,              # Event date (DD/MM/YYYY)
            "4": load_in_time_display,            # Load-in time (HH:MM)
            "5": show_time_display,               # Show time (HH:MM)
            "6": employee_first_name,             # Opening employee first name
            "7": normalized_emp_phone,            # Opening employee phone (E.164)
        }
        
        # 8. Build metadata for logging/debugging
        opening_employee_metadata = {
            "employee_id": opening_shift.get("employee_id"),
            "employee_name": employee_name,
            "employee_phone": normalized_emp_phone,
            "call_time": earliest_time.isoformat() if earliest_time else None,
            "shift_id": opening_shift.get("shift_id"),
        }
        
        return {
            "to_phone": to_phone,
            "variables": variables,
            "opening_employee_metadata": opening_employee_metadata,
        }

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
    def _format_time_israel(value: Any) -> str:
        """Format time value as HH:MM string in Israel timezone."""
        if isinstance(value, time):
            return value.strftime("%H:%M")

        if isinstance(value, datetime):
            # Use centralized utility to convert UTC to local time string
            return utc_to_local_time_str(value)

        return ""

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
            technical_name = event_dict.get("technical_name")
            technical_phone = event_dict.get("technical_phone")

            if technical_contact_id and (technical_name is None or technical_phone is None):
                technical_contact = self.contacts.get_contact_by_id(
                    org_id=org_id, contact_id=technical_contact_id
                )
                event_dict["technical_name"] = technical_name or self._get_contact_value(
                    technical_contact, "name"
                )
                event_dict["technical_phone"] = technical_phone or self._get_contact_value(
                    technical_contact, "phone"
                )
            else:
                event_dict["technical_name"] = technical_name
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

        # Add message delivery status
        event_dict["init_sent_at"] = self.messages.get_last_sent_at_for_content(
            org_id=org_id,
            event_id=event_id,
            content_sid=CONTENT_SID_INIT,
        )
        
        # Get latest delivery status for this event
        latest_status_by_event = self.messages.get_latest_status_by_event(org_id)
        event_dict["latest_delivery_status"] = latest_status_by_event.get(event_id)

        return event_dict

    def update_event_with_contacts(
        self,
        *,
        org_id: int,
        event_id: int,
        event_name: Optional[str] = None,
        event_date_str: Optional[str] = None,
        show_time_str: Optional[str] = _NO_UPDATE,
        load_in_time_str: Optional[str] = _NO_UPDATE,
        producer_name: Optional[str] = None,
        producer_phone: Optional[str] = None,
        producer_contact_id: Optional[int] = None,
        technical_name: Optional[str] = None,
        technical_phone: Optional[str] = None,
        technical_contact_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> None:
        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        if not event:
            raise ValueError("Event not found")

        # Build update parameters - only update what was provided
        update_params = {}
        
        # Handle name
        if event_name is not None:
            update_params["name"] = event_name
        
        # Handle dates/times
        if event_date_str is not None:
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            update_params["event_date"] = event_date
        else:
            event_date = event.get("event_date")
        
        if show_time_str is not _NO_UPDATE:
            update_params["show_time"] = self._combine_time(event_date, show_time_str)
        
        if load_in_time_str is not _NO_UPDATE:
            update_params["load_in_time"] = self._combine_time(event_date, load_in_time_str)
        
        # Handle producer contact
        if producer_contact_id is not None:
            # Explicit contact ID provided (from dropdown)
            update_params["producer_contact_id"] = producer_contact_id
        elif producer_name is not None or producer_phone is not None:
            # Name/phone provided (legacy inline edit)
            update_params["producer_contact_id"] = self._ensure_event_contact(
                org_id=org_id,
                existing_contact_id=event.get("producer_contact_id"),
                name=producer_name,
                phone=producer_phone,
                role="producer",
            )
        
        # Handle technical contact
        if technical_contact_id is not None:
            # Explicit contact ID provided (from dropdown)
            update_params["technical_contact_id"] = technical_contact_id
        elif technical_name is not None or technical_phone is not None:
            # Name/phone provided (legacy inline edit)
            update_params["technical_contact_id"] = self._ensure_event_contact(
                org_id=org_id,
                existing_contact_id=event.get("technical_contact_id"),
                name=technical_name,
                phone=technical_phone,
                role="technical",
            )
        
        # Handle notes
        if notes is not None:
            update_params["notes"] = notes
        
        # Only update if there are changes
        if update_params:
            self.events.update_event(
                org_id=org_id,
                event_id=event_id,
                **update_params
            )

    @staticmethod
    def _combine_time(event_date: date, time_str: Optional[str]):
        """
        Combine date and time string (HH:MM) to create UTC datetime.
        
        Input time is treated as Israel local time and converted to UTC.
        This ensures correct storage in TIMESTAMPTZ columns and handles DST automatically.
        """
        if not time_str:
            return None

        # Use centralized utility to parse local Israel time to UTC
        return parse_local_time_to_utc(event_date, time_str)

    def _ensure_event_contact(
        self,
        *,
        org_id: int,
        existing_contact_id: Optional[int],
        name: Optional[str],
        phone: Optional[str],
        role: str,
    ) -> Optional[int]:
        """Resolve and update a contact for an event without breaking phone uniqueness."""

        contact_id = existing_contact_id

        if phone:
            existing_by_phone = self.contacts.get_contact_by_phone(
                org_id=org_id, phone=phone
            )

            if existing_by_phone:
                contact_id = existing_by_phone.get("contact_id")
                self.contacts.update_contact(
                    org_id=org_id,
                    contact_id=contact_id,
                    name=name if name else None,
                    role=role,
                )
            elif contact_id:
                self.contacts.update_contact(
                    org_id=org_id,
                    contact_id=contact_id,
                    name=name if name else None,
                    phone=phone,
                    role=role,
                )
            else:
                contact_id = self.contacts.get_or_create_by_phone(
                    org_id=org_id,
                    phone=phone,
                    name=name or phone,
                    role=role,
                )
        elif name and contact_id:
            self.contacts.update_contact(
                org_id=org_id,
                contact_id=contact_id,
                name=name,
                role=role,
            )

        return contact_id

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
        """
        Send INIT WhatsApp message for an event.
        PHASE 4: Send to technical_contact if exists and has valid phone, otherwise producer.
        """
        event = self.events.get_event_by_id(org_id=org_id, event_id=event_id)
        if not event:
            raise ValueError("Event not found")

        org = self.orgs.get_org_by_id(org_id)
        if not org:
            raise ValueError("Org not found")

        # PHASE 4: Determine recipient - Technical first, then Producer
        recipient_contact_id = None
        recipient_type = None
        
        if contact_id:
            # Explicit contact_id provided (override)
            recipient_contact_id = contact_id
            recipient_type = "explicit"
        else:
            # PHASE 4: Prefer technical_contact, fallback to producer
            technical_contact_id = event.get("technical_contact_id")
            producer_contact_id = event.get("producer_contact_id")
            
            # Try technical first
            if technical_contact_id:
                technical_contact = self.contacts.get_contact_by_id(
                    org_id=org_id, contact_id=technical_contact_id
                )
                if technical_contact:
                    technical_phone = self._get_contact_value(technical_contact, "phone")
                    if technical_phone and technical_phone.strip():
                        recipient_contact_id = technical_contact_id
                        recipient_type = "technical"
                        logger.info(
                            "MESSAGE_ROUTING: Sending to technical contact",
                            extra={
                                "event_id": event_id,
                                "contact_id": technical_contact_id,
                                "phone": technical_phone,
                            }
                        )
            
            # Fallback to producer if no valid technical
            if not recipient_contact_id and producer_contact_id:
                recipient_contact_id = producer_contact_id
                recipient_type = "producer"
                logger.info(
                    "MESSAGE_ROUTING: Sending to producer contact (no valid technical)",
                    extra={
                        "event_id": event_id,
                        "contact_id": producer_contact_id,
                    }
                )
        
        if not recipient_contact_id:
            raise ValueError("Event missing contact_id; cannot send INIT (no technical or producer)")

        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=recipient_contact_id)
        if not contact:
            raise ValueError(f"{recipient_type.capitalize()} contact not found")

        original_phone = self._get_contact_value(contact, "phone")
        normalized_phone = normalize_phone_to_e164_il(original_phone)
        if not normalized_phone:
            raise ValueError("Valid phone number is missing")

        if normalized_phone != original_phone:
            self.contacts.update_contact_phone(
                org_id=org_id, contact_id=recipient_contact_id, phone=normalized_phone
            )

        conversation_id = self._ensure_conversation(org_id, event_id, recipient_contact_id)

        event_date = event.get("event_date")
        show_time = event.get("show_time")
        show_time = utc_to_local_time_str(show_time) if show_time else None

        event_date_str = event_date.strftime("%d.%m.%Y") if event_date else ""
        # show_time_str = show_time.strftime("%H:%M") if show_time else ""
        
        init_vars = {
            "1": self._get_contact_value(contact, "name") or recipient_type.capitalize(),
            "2": event.get("name") or "",
            "3": event_date_str,
            "4": show_time,
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
            "recipient_type": recipient_type,  # PHASE 4: Track recipient type
            "recipient_phone": normalized_phone,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=recipient_contact_id,
            direction="outgoing",
            body=f"INIT sent for event {event_id} to {recipient_type}",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )
        
        # Update conversation state after successful send
        self.conversations.update_conversation_state(
            org_id=org_id,
            conversation_id=conversation_id,
            expected_input="interactive",
            last_prompt_key="init",
            last_template_sid=CONTENT_SID_INIT,
            last_template_vars=init_vars,
        )
        
        logger.info(
            "MESSAGE_ROUTING: INIT sent successfully",
            extra={
                "event_id": event_id,
                "recipient_type": recipient_type,
                "recipient_contact_id": recipient_contact_id,
                "whatsapp_sid": whatsapp_sid,
            }
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
        
        # Update conversation state after successful send
        self.conversations.update_conversation_state(
            org_id=org_id,
            conversation_id=conversation_id,
            expected_input="interactive",
            last_prompt_key="ranges",
            last_template_sid=CONTENT_SID_RANGES,
            last_template_vars=variables,
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
        
        # Update conversation state after successful send
        self.conversations.update_conversation_state(
            org_id=org_id,
            conversation_id=conversation_id,
            expected_input="interactive",
            last_prompt_key="halves",
            last_template_sid=CONTENT_SID_HALVES,
            last_template_vars=variables,
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
        show_time = utc_to_local_time_str(show_time) if show_time else None

        event_date_str = event_date.strftime("%d.%m.%Y") if event_date else ""
        # show_time_str = show_time.strftime("%H:%M") if show_time else ""

        variables = {
            "event_name": event.get("name") or "",
            "event_date": event_date_str,
            "show_time":  show_time,
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
        
        # Update conversation state after successful send
        # Confirmation requires button click (confirm or go back)
        self.conversations.update_conversation_state(
            org_id=org_id,
            conversation_id=conversation_id,
            expected_input="interactive",
            last_prompt_key="confirm",
            last_template_sid=CONTENT_SID_CONFIRM,
            last_template_vars=variables,
        )

    async def run_due_followups(self, org_id: int = 1) -> int:
        now = now_utc()
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
                # Additional fields for list responses
                data.get("ListId"),
                data.get("Title"),
                data.get("Description"),
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
            # Special case: if we have an interactive value but couldn't resolve context,
            # this might be a button click on an old message - log and exit
            if interactive_value:
                logger.warning(
                    "Interactive payload missing event id or conversation context",
                    extra={"payload": payload, "has_interactive": bool(interactive_value)}
                )
            return

        conversation_id = conversation.get("conversation_id")
        
        # ============================================================
        # STATE MACHINE GUARD - EARLY VALIDATION
        # ============================================================
        # Determine message type
        # An interactive message is one that has interactive_value (button/list selection)
        # OR if Twilio indicates it's an interactive message type
        message_type = payload.get("MessageType", "").lower()
        is_interactive = bool(interactive_value) or message_type in ("button", "list", "interactive")
        is_contact_share = self._is_contact_share(payload)
        is_text_only = not is_interactive and not is_contact_share and bool(message_body)
        
        # Get current conversation state
        expected_input = conversation.get("expected_input", "interactive")
        last_prompt_key = conversation.get("last_prompt_key")
        
        logger.info(
            "STATE_GUARD: Message analysis",
            extra={
                "event_id": event_id,
                "contact_id": contact_id,
                "expected_input": expected_input,
                "is_interactive": is_interactive,
                "is_contact_share": is_contact_share,
                "is_text_only": is_text_only,
                "last_prompt_key": last_prompt_key,
                "interactive_value": interactive_value[:50] if interactive_value else None,
                "message_body": message_body[:50] if message_body else None,
                "message_type": payload.get("MessageType"),
            }
        )
        
        # GUARD RULE: Paused state - ignore all messages
        if expected_input == "paused":
            logger.info(
                "STATE_GUARD: Conversation paused, ignoring message",
                extra={"event_id": event_id, "contact_id": contact_id}
            )
            return
        
        # GUARD RULE: Interactive expected + text only received
        if expected_input == "interactive" and is_text_only:
            logger.warning(
                "STATE_GUARD: Blocked text input, interactive expected",
                extra={
                    "event_id": event_id,
                    "contact_id": contact_id,
                    "last_prompt_key": last_prompt_key,
                    "body": message_body[:50],
                }
            )
            
            # Send error message only - do NOT resend template
            # User should use buttons from the message they already have
            contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
            if contact:
                try:
                    # Different message for confirmation stage
                    if last_prompt_key == "confirm":
                        error_message = "נא לאשר או לחזור אחורה"
                    else:
                        error_message = "נא להשתמש בכפתורים"
                    
                    twilio_client.send_text(
                        to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
                        body=error_message,
                    )
                except Exception as e:
                    logger.error("STATE_GUARD: Failed to send error message", exc_info=e)
            
            # Don't resend template - user should use existing message
            return
        
        # GUARD RULE: Contact required
        if expected_input == "contact_required":
            if is_contact_share:
                # Valid contact share - continue normal flow
                logger.info(
                    "STATE_GUARD: Valid contact share received",
                    extra={"event_id": event_id, "contact_id": contact_id}
                )
            elif is_text_only:
                # Text received - try to extract phone number
                phone_numbers = self._extract_phone_numbers_from_text(message_body)
                
                logger.info(
                    "STATE_GUARD: Extracted phones from text",
                    extra={
                        "event_id": event_id,
                        "contact_id": contact_id,
                        "phone_count": len(phone_numbers),
                        "body": message_body[:50],
                    }
                )
                
                if len(phone_numbers) == 0:
                    # No phone found - send error message (no resend needed, message is clear)
                    logger.warning(
                        "STATE_GUARD: No phone in text, contact required",
                        extra={"event_id": event_id, "body": message_body[:50]}
                    )
                    
                    contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
                    if contact:
                        try:
                            twilio_client.send_text(
                                to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
                                body="יש לצרף איש קשר או לכתוב שם מלא וטלפון בהודעה אחת",
                            )
                        except Exception as e:
                            logger.error("STATE_GUARD: Failed to send error message", exc_info=e)
                    
                    # Don't resend - the message already contains full instructions
                    return
                
                elif len(phone_numbers) >= 2:
                    # Multiple phones found - send error message (no resend needed)
                    logger.warning(
                        "STATE_GUARD: Multiple phones in text, need exactly one",
                        extra={"event_id": event_id, "phone_count": len(phone_numbers)}
                    )
                    
                    contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
                    if contact:
                        try:
                            twilio_client.send_text(
                                to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
                                body="יש לצרף איש קשר או לכתוב שם מלא וטלפון בהודעה אחת",
                            )
                        except Exception as e:
                            logger.error("STATE_GUARD: Failed to send error message", exc_info=e)
                    
                    # Don't resend - the message already contains full instructions
                    return
                
                else:
                    # Exactly 1 phone - treat as contact share
                    logger.info(
                        "STATE_GUARD: Single phone in text, treating as contact share",
                        extra={"event_id": event_id, "phone": phone_numbers[0]}
                    )
                    # Create synthetic payload for contact handling
                    payload["Contacts[0][PhoneNumber]"] = phone_numbers[0]
                    payload["Contacts[0][Name]"] = message_body.split()[0] if message_body else phone_numbers[0]
        
        # ============================================================
        # END STATE MACHINE GUARD
        # ============================================================

        received_at = now_utc()
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
    def _is_contact_share(payload: dict) -> bool:
        """Check if payload contains a contact share (vCard or Twilio Contacts)."""
        if not payload:
            return False
        
        # Check for Twilio Contacts array
        if payload.get("Contacts[0][PhoneNumber]") or payload.get("Contacts[0][WaId]"):
            return True
        
        # Check for vCard media
        try:
            num_media = int(payload.get("NumMedia") or payload.get("numMedia") or 0)
        except (TypeError, ValueError):
            num_media = 0
        
        if num_media > 0:
            for idx in range(num_media):
                content_type = (
                    payload.get(f"MediaContentType{idx}")
                    or payload.get(f"mediaContentType{idx}")
                    or ""
                )
                filename = (
                    payload.get(f"MediaFilename{idx}")
                    or payload.get(f"mediaFilename{idx}")
                    or ""
                )
                if "vcard" in content_type.lower() or filename.lower().endswith(".vcf"):
                    return True
        
        return False
    
    async def _resend_last_prompt(
        self,
        org_id: int,
        event_id: int,
        contact_id: int,
        conversation_id: int,
        last_prompt_key: Optional[str],
    ) -> None:
        """Resend the last prompt to user based on last_prompt_key."""
        logger.info(
            "STATE_GUARD: Resending last prompt",
            extra={
                "event_id": event_id,
                "contact_id": contact_id,
                "last_prompt_key": last_prompt_key,
            }
        )
        
        try:
            if last_prompt_key == "ranges":
                await self.send_ranges_for_event(org_id, event_id, contact_id)
            elif last_prompt_key == "halves":
                # Get range_id from pending_data_fields
                conversation = self.conversations.get_conversation_by_id(org_id, conversation_id)
                pending = (conversation or {}).get("pending_data_fields") or {}
                range_id = pending.get("last_range_id") or 1
                await self.send_halves_for_event_range(org_id, event_id, contact_id, range_id)
            elif last_prompt_key == "contact_prompt":
                # Resend contact request text (not template)
                contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
                if contact:
                    twilio_resp = twilio_client.send_text(
                        to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
                        body="יש לצרף איש קשר או לכתוב שם מלא וטלפון בהודעה אחת",
                    )
                    whatsapp_sid = getattr(twilio_resp, "sid", None) if twilio_resp else None
                    self.messages.log_message(
                        org_id=org_id,
                        conversation_id=conversation_id,
                        event_id=event_id,
                        contact_id=contact_id,
                        direction="outgoing",
                        body="Resent contact request text (guard)",
                        whatsapp_msg_sid=whatsapp_sid,
                        raw_payload={"resend_reason": "guard_validation"},
                    )
            elif last_prompt_key == "init":
                # After INIT, don't resend INIT - user should use the buttons in the original INIT message
                # The warning message has already been sent by the caller
                logger.info(
                    "STATE_GUARD: Not resending INIT, user should use buttons from original message",
                    extra={"event_id": event_id, "contact_id": contact_id}
                )
            elif not last_prompt_key:
                # No prompt key set - fallback to init (shouldn't happen normally)
                logger.warning(
                    "STATE_GUARD: No last_prompt_key set, sending init as fallback",
                    extra={"event_id": event_id, "contact_id": contact_id}
                )
                await self.send_init_for_event(event_id=event_id, org_id=org_id, contact_id=contact_id)
            else:
                logger.warning(
                    "STATE_GUARD: Unknown prompt key",
                    extra={"last_prompt_key": last_prompt_key}
                )
        except Exception as e:
            logger.error(
                "STATE_GUARD: Failed to resend prompt",
                exc_info=e,
                extra={"last_prompt_key": last_prompt_key, "event_id": event_id}
            )

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
    def _extract_phone_numbers_from_text(text: str) -> list[str]:
        """
        Extract all phone numbers from text.
        Returns list of normalized phone numbers (E.164 format).
        Used for contact_required state validation.
        """
        if not text:
            return []
        
        # Find all potential phone numbers
        # Patterns: +972..., 972..., 05..., 5...
        phone_pattern = r"[+]?[\d][\d\s()\-]{7,}"
        matches = re.findall(phone_pattern, text)
        
        normalized_phones = []
        for match in matches:
            # Try to normalize
            normalized = normalize_phone_to_e164_il(match.strip())
            # Validate it looks like a real phone (starts with + and has reasonable length)
            if normalized and normalized.startswith("+") and len(normalized) >= 10:
                normalized_phones.append(normalized)
        
        return normalized_phones

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
        """
        PHASE 1: Handle "אני לא יודע" (NOT_SURE) action.
        Updates event status to 'follow_up', calculates next_followup_at,
        and sends acknowledgment message to client.
        """
        logger.info(
            "FOLLOW_UP: Detected 'אני לא יודע' action",
            extra={
                "event_id": event_id,
                "contact_id": contact_id,
                "conversation_id": conversation_id,
                "action": "follow_up_detected",
            }
        )
        
        followup_at = now_utc() + timedelta(hours=72)
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

        # PHASE 1: Update event status to follow_up and set next_followup_at
        try:
            self.events.update_event(
                org_id=org_id,
                event_id=event_id,
                status="follow_up",
                next_followup_at=followup_at,
            )
            logger.info(
                "FOLLOW_UP: Event status updated to 'follow_up'",
                extra={
                    "event_id": event_id,
                    "next_followup_at": followup_at.isoformat(),
                }
            )
        except Exception as e:
            logger.error(
                "FOLLOW_UP: Failed to update event status",
                exc_info=e,
                extra={"event_id": event_id}
            )
            # Continue with sending ack even if DB update fails
        
        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        if not contact:
            logger.error(
                "FOLLOW_UP: Contact not found, cannot send acknowledgment",
                extra={"contact_id": contact_id, "event_id": event_id}
            )
            return

        # Send acknowledgment message to client
        try:
            twilio_resp = twilio_client.send_content_message(
                to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
                content_sid=CONTENT_SID_NOT_SURE,
                content_variables={},
            )
            whatsapp_sid = getattr(twilio_resp, "sid", None)
            
            if whatsapp_sid:
                logger.info(
                    "FOLLOW_UP: Acknowledgment message sent successfully",
                    extra={
                        "event_id": event_id,
                        "contact_id": contact_id,
                        "whatsapp_sid": whatsapp_sid,
                        "action": "follow_up_ack_sent",
                    }
                )
            else:
                logger.warning(
                    "FOLLOW_UP: Message sent but no SID returned",
                    extra={"event_id": event_id, "contact_id": contact_id}
                )
        except Exception as e:
            logger.error(
                "FOLLOW_UP: Failed to send acknowledgment message",
                exc_info=e,
                extra={
                    "event_id": event_id,
                    "contact_id": contact_id,
                    "phone": self._get_contact_value(contact, "phone"),
                }
            )
            # Don't raise - we want to log the message even if send fails
            whatsapp_sid = None

        raw_payload = {
            "content_sid": CONTENT_SID_NOT_SURE,
            "variables": {},
            "twilio_message_sid": whatsapp_sid,
        }

        # Log the outgoing message
        try:
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
            logger.info(
                "FOLLOW_UP: Message logged successfully",
                extra={"event_id": event_id, "message_id": whatsapp_sid}
            )
        except Exception as e:
            logger.error(
                "FOLLOW_UP: Failed to log outgoing message",
                exc_info=e,
                extra={"event_id": event_id}
            )
        
        # Update conversation state to paused - no more automation
        try:
            self.conversations.update_conversation_state(
                org_id=org_id,
                conversation_id=conversation_id,
                expected_input="paused",
                last_prompt_key="not_sure",
                last_template_sid=CONTENT_SID_NOT_SURE,
                last_template_vars={},
            )
            logger.info(
                "FOLLOW_UP: Conversation state set to paused",
                extra={"event_id": event_id, "conversation_id": conversation_id}
            )
        except Exception as e:
            logger.error(
                "FOLLOW_UP: Failed to update conversation state",
                exc_info=e,
                extra={"event_id": event_id}
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

        # Send simple text message instead of template
        twilio_resp = twilio_client.send_text(
            to=normalize_phone_to_e164_il(self._get_contact_value(contact, "phone")),
            body="יש לצרף איש קשר או לכתוב שם מלא וטלפון בהודעה אחת",
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None) if twilio_resp else None

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
            "type": "contact_request_text",
            "body": "יש לצרף איש קשר או לכתוב שם מלא וטלפון בהודעה אחת",
            "twilio_message_sid": whatsapp_sid,
        }

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body="Sent contact request text (NOT CONTACT flow)",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload=raw_payload,
        )
        
        # Update conversation state to expect contact
        self.conversations.update_conversation_state(
            org_id=org_id,
            conversation_id=conversation_id,
            expected_input="contact_required",
            last_prompt_key="contact_prompt",
            last_template_sid=None,  # No template, just text
            last_template_vars={},
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
            # Parse local Israel time to UTC for storage
            load_in_dt = parse_local_time_to_utc(event_date, f"{hour:02d}:{minute:02d}")
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

    def get_technical_suggestions_for_producer(
        self, org_id: int, producer_contact_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get suggested technical contacts based on producer history.
        Returns contacts who have worked with this producer before,
        sorted by frequency and recency.
        """
        from sqlalchemy import text
        from app.appdb import get_session

        query = text("""
            WITH all_events AS (
                -- Get all events where this producer worked with technical contacts
                SELECT 
                    e.technical_contact_id,
                    COUNT(*) as times_worked
                FROM events e
                WHERE e.org_id = :org_id
                  AND e.producer_contact_id = :producer_contact_id
                  AND e.technical_contact_id IS NOT NULL
                GROUP BY e.technical_contact_id
            ),
            recent_events AS (
                -- Get the most recent event for each technical contact
                SELECT 
                    e.technical_contact_id,
                    e.name as event_name,
                    e.event_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY e.technical_contact_id 
                        ORDER BY e.event_date DESC
                    ) as rn
                FROM events e
                WHERE e.org_id = :org_id
                  AND e.producer_contact_id = :producer_contact_id
                  AND e.technical_contact_id IS NOT NULL
            )
            SELECT 
                c.contact_id,
                c.name,
                c.phone,
                re.event_name as last_event_name,
                re.event_date as last_event_date,
                ae.times_worked
            FROM all_events ae
            JOIN recent_events re ON re.technical_contact_id = ae.technical_contact_id
            JOIN contacts c ON c.contact_id = ae.technical_contact_id
            WHERE re.rn = 1
            ORDER BY ae.times_worked DESC, re.event_date DESC
            LIMIT 10
        """)

        with get_session() as session:
            result = session.execute(
                query,
                {"org_id": org_id, "producer_contact_id": producer_contact_id},
            )
            rows = result.mappings().all()
            return [dict(row) for row in rows]
