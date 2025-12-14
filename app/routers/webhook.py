import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.dependencies import get_db_session, get_hoh_service
from app.hoh_service import HOHService
from app.repositories import (
    MessageDeliveryLogRepository,
    MessageStatusRepository,
)
from app.utils.delivery_status import normalize_delivery_status

logger = logging.getLogger(__name__)

router = APIRouter()
delivery_logs = MessageDeliveryLogRepository()
message_status_repo = MessageStatusRepository()


async def _extract_payload(request: Request) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    try:
        form_data = await request.form()
        payload = {k: v for k, v in form_data.items()}
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

    return payload


@router.post("/twilio-status")
async def twilio_status_callback(
    request: Request, session: Session = Depends(get_db_session)
):
    payload = await _extract_payload(request)

    message_sid = (
        payload.get("MessageSid")
        or payload.get("messagesid")
        or payload.get("message_sid")
    )
    message_status = (
        payload.get("MessageStatus")
        or payload.get("message_status")
        or payload.get("SmsStatus")
    )
    error_code = payload.get("ErrorCode") or payload.get("error_code")
    error_message = payload.get("ErrorMessage") or payload.get("error_message")

    if not message_sid:
        logger.warning("Twilio status callback missing MessageSid: %s", payload)
        return Response(status_code=204)

    message = message_status_repo.get_by_whatsapp_sid(session, message_sid)
    if not message:
        logger.warning("No message found for Twilio SID %s", message_sid)
        return Response(status_code=204)

    normalized_status = normalize_delivery_status(message_status)
    delivery_logs.log_status(
        session,
        org_id=message.org_id,
        message_id=message.message_id,
        status=normalized_status,
        error_code=error_code,
        error_message=error_message,
        provider_payload=payload,
    )

    return Response(status_code=204)


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
