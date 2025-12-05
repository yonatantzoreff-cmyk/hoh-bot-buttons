# app/hoh_service.py
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.repositories import (
    EventRepository,
    ContactRepository,
    ConversationRepository,
    MessageRepository,
)
from app import twilio_client
from app.flows.slots import generate_half_hour_slots


class HOHService:
    def __init__(self):
        self.events = EventRepository()
        self.contacts = ContactRepository()
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()

    # Twilio button/action payload convention:
    #   - All payloads must include the event id using the pattern *_EVT_<event_id>.
    #   - Slot selections also include the slot index: SLOT_<index>_EVT_<event_id>.
    # This ensures we never guess an event based only on the sender phone number.

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
            "no_times_action": f"NOT_SURE_EVT_{event_id}",
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

    async def handle_whatsapp_webhook(self, payload: dict, org_id: int = 1) -> None:
        """
        Handle an incoming Twilio WhatsApp webhook payload, update DB state,
        and send any required replies via Twilio's Content API.
        """

        def _pick_interactive_value(data: Dict[str, Any]) -> str:
            return (
                (data.get("ButtonPayload") or "").strip()
                or (data.get("ListItemValue") or "").strip()
                or (data.get("ButtonText") or "").strip()
                or (data.get("ListItemTitle") or "").strip()
            )

        interactive_value = _pick_interactive_value(payload)
        action_data = (
            self._parse_action_payload(interactive_value) if interactive_value else {}
        )

        from_number = (payload.get("From") or payload.get("WaId") or "").strip()
        message_body = (payload.get("Body") or "").strip()

        contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id,
            phone=from_number,
            name=payload.get("ProfileName") or from_number,
            role="producer",
        )

        event_id: Optional[int] = action_data.get("event_id")
        conversation = None
        event = None

        if interactive_value and not event_id:
            # Interactive payloads must carry event id; do not guess from phone number.
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

        action = (action_data.get("action") or "").upper()

        if action == "CHOOSE_TIME":
            await self._send_slot_list(
                event=event,
                contact_id=contact_id,
                org_id=org_id,
                conversation_id=conversation_id,
            )
            return

        if action == "SLOT":
            await self._handle_slot_selection(
                action=interactive_value,
                event=event,
                contact_id=contact_id,
                conversation_id=conversation_id,
                org_id=org_id,
                slot_index=action_data.get("slot_index"),
            )
            return

        if action == "CONFIRM_SLOT":
            await self._apply_confirmed_slot(
                event_id=event_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
                org_id=org_id,
            )
            return

        if action == "CHANGE_SLOT":
            await self._send_slot_list(
                event=event,
                contact_id=contact_id,
                org_id=org_id,
                conversation_id=conversation_id,
            )
            return

        if action == "NOT_SURE":
            await self._handle_not_sure(
                event_id=event_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                org_id=org_id,
            )
            return

        if action == "NOT_CONTACT":
            await self._handle_not_contact(
                event_id=event_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                org_id=org_id,
            )
            return

        await self._handle_contact_followup(
            body_text=message_body,
            event_id=event_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            org_id=org_id,
        )

    def _parse_action_payload(self, payload: str) -> dict:
        """
        Parse a button/action payload to extract the action name, event id, and slot index.

        Expected formats:
            - "CHOOSE_TIME_EVT_<event_id>"
            - "CONFIRM_SLOT_EVT_<event_id>"
            - "CHANGE_SLOT_EVT_<event_id>"
            - "NOT_SURE_EVT_<event_id>"
            - "NOT_CONTACT_EVT_<event_id>"
            - "SLOT_<index>_EVT_<event_id>"

        Returns a dictionary such as:
            {"action": "CHOOSE_TIME", "event_id": 123, "slot_index": None}
            {"action": "SLOT", "event_id": 42, "slot_index": 3}
            {"action": "UNKNOWN"} on parse failure.
        """

        result: Dict[str, Any] = {"action": "UNKNOWN"}
        if not payload:
            return result

        try:
            left, evt_part = payload.split("_EVT_", 1)
            event_id = int(evt_part)
        except (ValueError, AttributeError):
            return result

        left = (left or "").upper()
        result["event_id"] = event_id

        if left.startswith("SLOT_"):
            try:
                _, idx_str = left.split("_", 1)
                slot_index = int(idx_str)
            except (ValueError, IndexError):
                return result

            result.update({"action": "SLOT", "slot_index": slot_index})
            return result

        if left in {
            "CHOOSE_TIME",
            "CONFIRM_SLOT",
            "CHANGE_SLOT",
            "NOT_SURE",
            "NOT_CONTACT",
        }:
            result.update({"action": left, "slot_index": None})

        return result

    async def _handle_contact_followup(
        self,
        body_text: str,
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

        digits = re.findall(r"\+?\d{9,15}", body_text)
        phone = digits[0] if digits else body_text.strip()
        name = body_text.strip()

        new_contact_id = self.contacts.get_or_create_by_phone(
            org_id=org_id,
            phone=phone,
            name=name,
            role="producer",
        )

        self.events.update_event_fields(
            org_id=org_id, event_id=event_id, producer_contact_id=new_contact_id
        )

        new_conv = self.conversations.get_open_conversation(
            org_id=org_id, event_id=event_id, contact_id=new_contact_id
        )
        if not new_conv:
            new_conv_id = self.conversations.create_conversation(
                org_id=org_id,
                event_id=event_id,
                contact_id=new_contact_id,
                channel="whatsapp",
                status="open",
            )
        else:
            new_conv_id = new_conv.get("conversation_id")

        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields={},
        )

        await self.send_init_for_event(event_id=event_id, org_id=org_id)

        self.messages.log_message(
            org_id=org_id,
            conversation_id=new_conv_id,
            event_id=event_id,
            contact_id=new_contact_id,
            direction="outgoing",
            body="Sent new INIT to updated contact",
        )

    async def _handle_not_sure(
        self,
        event_id: int,
        contact_id: int,
        conversation_id: int,
        org_id: int,
    ) -> None:
        content_sid = os.getenv("CONTENT_SID_NOT_SURE_QR")
        if not content_sid:
            return

        twilio_resp = twilio_client.send_content_message(
            to=self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id).get(
                "phone"
            ),
            content_sid=content_sid,
            variables={},
            channel="whatsapp",
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None)

        self.events.update_event_fields(
            org_id=org_id, event_id=event_id, status="waiting_for_reply"
        )

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body="Sent NOT_SURE follow-up",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload={"content_sid": content_sid},
        )

    async def _handle_not_contact(
        self,
        event_id: int,
        contact_id: int,
        conversation_id: int,
        org_id: int,
    ) -> None:
        content_sid = os.getenv("CONTENT_SID_CONTACT_QR")
        if not content_sid:
            return

        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        twilio_resp = twilio_client.send_content_message(
            to=contact.get("phone"),
            content_sid=content_sid,
            variables={},
            channel="whatsapp",
        )

        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields={"awaiting_new_contact": True},
        )

        whatsapp_sid = getattr(twilio_resp, "sid", None)
        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body="Requested alternate contact",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload={"content_sid": content_sid},
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
        selected = pending.get("selected_slot") or {}
        selected_iso = selected.get("datetime")

        load_in_time = None
        if selected_iso:
            try:
                load_in_time = datetime.fromisoformat(selected_iso)
            except ValueError:
                load_in_time = None

        self.events.update_event_fields(
            org_id=org_id,
            event_id=event_id,
            load_in_time=load_in_time,
            status="confirmed",
        )

        if conversation:
            self.conversations.update_status(
                org_id=org_id, conversation_id=conversation_id, status="closed"
            )

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=event_id,
            contact_id=contact_id,
            direction="outgoing",
            body="Slot confirmed",
        )

    async def _handle_slot_selection(
        self,
        action: str,
        *,
        event,
        contact_id: int,
        conversation_id: int,
        org_id: int,
        slot_index: Optional[int] = None,
    ) -> None:
        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        slots = self._build_slots(event)
        pending_slots = {slot["id"]: slot for slot in slots}

        slot_id = action
        selected = pending_slots.get(slot_id)
        if not selected and slot_index:
            slot_key = f"SLOT_{slot_index}_EVT_{event.get('event_id')}"
            selected = pending_slots.get(slot_key)
        if not selected:
            selected = next(iter(pending_slots.values()), None)
        if not selected:
            return

        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields={"selected_slot": selected, "slots": slots},
        )

        content_sid = os.getenv("CONTENT_SID_CONFIRM_QR")
        if not content_sid:
            return

        variables = {
            "slot": selected["label"],
            "confirm_action": f"CONFIRM_SLOT_EVT_{selected['event_id']}",
            "change_slot_action": f"CHANGE_SLOT_EVT_{selected['event_id']}",
        }
        twilio_resp = twilio_client.send_content_message(
            to=contact.get("phone"),
            content_sid=content_sid,
            variables=variables,
            channel="whatsapp",
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None)

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=selected["event_id"],
            contact_id=contact_id,
            direction="outgoing",
            body=f"Sent confirm for slot {selected['label']}",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload={"content_sid": content_sid, "variables": variables},
        )

    async def _send_slot_list(
        self,
        *,
        event,
        contact_id: int,
        org_id: int,
        conversation_id: int,
    ) -> None:
        contact = self.contacts.get_contact_by_id(org_id=org_id, contact_id=contact_id)
        slots = self._build_slots(event)
        variables = {
            f"item{i+1}": slot["label"]
            for i, slot in enumerate(slots)
            if i < 10
        }
        variables.update(
            {f"id{i+1}": slot["id"] for i, slot in enumerate(slots) if i < 10}
        )

        content_sid = os.getenv("CONTENT_SID_SLOT_LIST")
        if not content_sid:
            return

        twilio_resp = twilio_client.send_content_message(
            to=contact.get("phone"),
            content_sid=content_sid,
            variables=variables,
            channel="whatsapp",
        )
        whatsapp_sid = getattr(twilio_resp, "sid", None)

        self.conversations.update_pending_data_fields(
            org_id=org_id,
            conversation_id=conversation_id,
            pending_data_fields={"slots": slots},
        )

        self.messages.log_message(
            org_id=org_id,
            conversation_id=conversation_id,
            event_id=slots[0]["event_id"] if slots else event.get("event_id"),
            contact_id=contact_id,
            direction="outgoing",
            body="Sent slot list",
            whatsapp_msg_sid=whatsapp_sid,
            raw_payload={"content_sid": content_sid, "variables": variables},
        )

    def _build_slots(self, event) -> List[Dict[str, Any]]:
        event_id = event.get("event_id") if event else None
        show_time = event.get("show_time") if event else None

        if show_time:
            start_dt = show_time - timedelta(hours=2)
        else:
            today = datetime.now(timezone.utc)
            start_dt = today.replace(hour=10, minute=0, second=0, microsecond=0)

        times = generate_half_hour_slots(
            start_dt.timetz(), (start_dt + timedelta(hours=4)).timetz()
        )
        slots: List[Dict[str, Any]] = []
        for idx, label in enumerate(times[:10], start=1):
            slot_dt = start_dt + timedelta(minutes=30 * (idx - 1))
            slots.append(
                {
                    "id": f"SLOT_{idx}_EVT_{event_id}",
                    "label": label,
                    "datetime": slot_dt.isoformat(),
                    "event_id": event_id,
                }
            )
        return slots
