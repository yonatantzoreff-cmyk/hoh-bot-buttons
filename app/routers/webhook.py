import json
import logging

from fastapi import APIRouter, Request, Depends, Response

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService

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
