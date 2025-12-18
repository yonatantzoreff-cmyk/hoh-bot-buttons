import json
import logging

from fastapi import APIRouter, Request, Depends, Response

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService
from app.repositories import MessageDeliveryLogRepository, MessageRepository
from app.pubsub import get_pubsub

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

    # Get message repo to broadcast after handling
    message_repo = MessageRepository()
    
    # Get the current max message_id before handling
    from app.appdb import get_session
    from sqlalchemy import text
    with get_session() as session:
        result = session.execute(text("SELECT COALESCE(MAX(message_id), 0) as max_id FROM messages WHERE org_id = :org_id"), {"org_id": 1})
        max_id_before = result.scalar_one()

    # Handle webhook
    await hoh.handle_whatsapp_webhook(payload, org_id=1)
    
    # Get the new message that was just created (if any)
    with get_session() as session:
        result = session.execute(
            text("""
                SELECT m.message_id, m.event_id, m.body, m.received_at,
                       e.name as event_name, e.event_date
                FROM messages m
                LEFT JOIN events e ON m.event_id = e.event_id
                WHERE m.org_id = :org_id 
                  AND m.message_id > :max_id_before
                  AND m.direction = 'incoming'
                ORDER BY m.message_id DESC
                LIMIT 1
            """),
            {"org_id": 1, "max_id_before": max_id_before}
        )
        new_message = result.mappings().first()
    
    # Broadcast the new message via SSE
    if new_message:
        pubsub = get_pubsub()
        await pubsub.publish("notifications", {
            "type": "incoming_message",
            "org_id": 1,
            "message_id": new_message["message_id"],
            "event_id": new_message["event_id"],
            "event_name": new_message["event_name"],
            "event_date": new_message["event_date"].isoformat() if new_message["event_date"] else None,
            "snippet": new_message["body"][:100] if new_message["body"] else "",
            "received_at": new_message["received_at"].isoformat() if new_message["received_at"] else None,
        })
        logger.info(f"Broadcast incoming message notification for event {new_message['event_id']}")
    
    return Response(status_code=204)


@router.post("/twilio-status")
async def twilio_status_callback(
    request: Request,
    delivery_repo: MessageDeliveryLogRepository = Depends(lambda: MessageDeliveryLogRepository()),
    message_repo: MessageRepository = Depends(lambda: MessageRepository()),
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
        payload = {}

    if not payload:
        try:
            payload = await request.json()
        except Exception:
            raw_body = await request.body()
            try:
                payload = json.loads(raw_body.decode()) if raw_body else {}
            except Exception:
                payload = {}

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
        return Response(status_code=200)

    # Find the message in our DB by whatsapp_msg_sid
    message = delivery_repo.get_message_by_whatsapp_sid(message_sid)

    updated = message_repo.update_message_timestamps_from_status(
        message_sid=message_sid, status=message_status
    )

    if not updated:
        logger.info(
            "No message record found to update for MessageSid",
            extra={"message_sid": message_sid},
        )

    if not message:
        if not updated:
            logger.info(
                "Message not found for MessageSid",
                extra={"message_sid": message_sid},
            )
        return Response(status_code=200)

    org_id = message.get("org_id")
    message_id = message.get("message_id")

    if not org_id or not message_id:
        logger.error(
            "Message found but missing org_id or message_id",
            extra={"message_sid": message_sid, "org_id": org_id, "message_id": message_id},
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
