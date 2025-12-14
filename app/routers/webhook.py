import json
import logging

from fastapi import APIRouter, Request, Depends, Response

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService
from app.repositories import MessageDeliveryLogRepository

logger = logging.getLogger(__name__)

router = APIRouter()


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
async def twilio_status_callback(
    request: Request,
    delivery_repo: MessageDeliveryLogRepository = Depends(lambda: MessageDeliveryLogRepository()),
):
    """
    Twilio Status Callback webhook for message delivery tracking.
    
    Twilio sends status updates for each message (queued, sent, delivered, failed, etc.)
    as application/x-www-form-urlencoded POST requests.
    
    See: https://www.twilio.com/docs/sms/api/message-resource#message-status-values
    """
    
    # Parse form data from Twilio
    payload: dict = {}
    try:
        form_data = await request.form()
        payload = dict(form_data)
    except Exception as e:
        logger.warning("Failed to parse Twilio status callback form data", exc_info=e)
        return Response(status_code=400, content="Invalid form data")

    # Extract key fields from Twilio's callback
    message_sid = payload.get("MessageSid") or payload.get("SmsSid")
    message_status = payload.get("MessageStatus")
    error_code = payload.get("ErrorCode")
    error_message = payload.get("ErrorMessage")

    logger.info(
        "Twilio status callback received",
        extra={
            "message_sid": message_sid,
            "status": message_status,
            "error_code": error_code,
        }
    )

    if not message_sid or not message_status:
        logger.warning(
            "Missing MessageSid or MessageStatus in Twilio callback",
            extra={"payload": payload}
        )
        return Response(status_code=400, content="Missing required fields")

    # Find the message in our DB by whatsapp_msg_sid
    message = delivery_repo.get_message_by_whatsapp_sid(message_sid)
    
    if not message:
        logger.warning(
            "Message not found for MessageSid",
            extra={"message_sid": message_sid}
        )
        # Return 200 to acknowledge receipt even if message not found
        # (could be a message we didn't track or from a different system)
        return Response(status_code=200)

    org_id = message.get("org_id")
    message_id = message.get("message_id")

    if not org_id or not message_id:
        logger.error(
            "Message found but missing org_id or message_id",
            extra={"message_sid": message_sid, "org_id": org_id, "message_id": message_id}
        )
        return Response(status_code=200)

    # Insert a new delivery log entry
    try:
        delivery_repo.create_delivery_log(
            org_id=org_id,
            message_id=message_id,
            status=message_status,
            error_code=error_code,
            error_message=error_message,
            provider="twilio",
            provider_payload=payload,
        )
        logger.info(
            "Delivery status logged successfully",
            extra={
                "message_id": message_id,
                "org_id": org_id,
                "status": message_status,
            }
        )
    except Exception as e:
        logger.error(
            "Failed to create delivery log entry",
            exc_info=e,
            extra={
                "message_id": message_id,
                "org_id": org_id,
                "status": message_status,
            }
        )
        # Return 200 anyway so Twilio doesn't retry
        return Response(status_code=200)

    return Response(status_code=200)
