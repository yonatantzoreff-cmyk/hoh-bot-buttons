import json
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Request, Depends, Response
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, get_hoh_service
from app.hoh_service import HOHService
from app.models import Message, MessageDeliveryLog

logger = logging.getLogger(__name__)

router = APIRouter()


_MESSAGE_DELIVERY_STATUS_COLUMN_PRESENT: Optional[bool] = None


def _normalize_twilio_status(raw_status: Optional[str]) -> Optional[str]:
    if not raw_status:
        return None

    normalized = raw_status.lower()
    if normalized == "sending":
        return "sent"
    if normalized == "undelivered":
        return "failed"
    return normalized


def _message_has_delivery_status_column(session: Session) -> bool:
    global _MESSAGE_DELIVERY_STATUS_COLUMN_PRESENT
    if _MESSAGE_DELIVERY_STATUS_COLUMN_PRESENT is not None:
        return _MESSAGE_DELIVERY_STATUS_COLUMN_PRESENT

    inspector = inspect(session.bind)
    columns = {col["name"] for col in inspector.get_columns("messages")}
    _MESSAGE_DELIVERY_STATUS_COLUMN_PRESENT = "delivery_status" in columns
    return _MESSAGE_DELIVERY_STATUS_COLUMN_PRESENT


def _update_message_delivery_status_if_supported(
    session: Session, message_id: int, normalized_status: str
) -> None:
    if not normalized_status:
        return

    if not _message_has_delivery_status_column(session):
        return

    session.execute(
        text(
            """
            UPDATE messages
            SET delivery_status = :status
            WHERE message_id = :message_id
            """
        ),
        {"status": normalized_status, "message_id": message_id},
    )


@router.post("/whatsapp-webhook")
async def whatsapp_webhook(
    request: Request,
    hoh: HOHService = Depends(get_hoh_service),
):
    payload: dict = {}
    try:
        form_data = await request.form()
        payload = dict(form_data)
    except Exception:  # pragma: no cover - defensive fallback
        payload = {}

    if not payload:
        try:
            payload = await request.json()
        except Exception:  # pragma: no cover - defensive fallback
            raw_body = await request.body()
            try:
                payload = json.loads(raw_body.decode()) if raw_body else {}
            except Exception:
                payload = {}

    body = (payload.get("Body") or payload.get("body") or "").strip()
    if not body:
        contact_summary = HOHService._contact_summary_from_payload(payload)
        if contact_summary:
            body = contact_summary
    logger.info("Incoming WhatsApp body: %s", body)

    await hoh.handle_whatsapp_webhook(payload, org_id=1)
    return Response(status_code=204)


@router.post("/twilio-status")
async def twilio_status_webhook(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    """Handle Twilio status callbacks for WhatsApp messages."""

    try:
        form_data = await request.form()
        payload: Dict[str, str] = dict(form_data)
    except Exception:  # pragma: no cover - defensive fallback
        payload = {}

    if not payload:
        try:
            payload = await request.json()
        except Exception:  # pragma: no cover - defensive fallback
            raw_body = await request.body()
            try:
                payload = json.loads(raw_body.decode()) if raw_body else {}
            except Exception:
                payload = {}

    message_sid = payload.get("MessageSid") or payload.get("messagesid")
    raw_status = payload.get("MessageStatus") or payload.get("messagestatus")
    error_code = payload.get("ErrorCode") or payload.get("errorcode")
    error_message = payload.get("ErrorMessage") or payload.get("errormessage")

    normalized_status = _normalize_twilio_status(raw_status)

    if not message_sid:
        logger.warning("Received Twilio status callback without MessageSid")
        return Response(status_code=204)

    message = session.scalar(
        select(Message)
            .where(Message.whatsapp_msg_sid == message_sid)
            .order_by(Message.message_id.desc())
            .limit(1)
    )

    if not message:
        logger.warning("Twilio status callback for unknown SID %s", message_sid)
        return Response(status_code=204)

    log_entry = MessageDeliveryLog(
        org_id=message.org_id,
        message_id=message.message_id,
        status=normalized_status or (raw_status or "unknown"),
        error_code=str(error_code) if error_code is not None else None,
        error_message=error_message,
        provider="twilio",
        provider_payload=payload,
    )
    session.add(log_entry)

    _update_message_delivery_status_if_supported(
        session=session, message_id=message.message_id, normalized_status=normalized_status or ""
    )

    return Response(status_code=204)
