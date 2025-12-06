import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/whatsapp-webhook")
async def whatsapp_webhook(
    request: Request,
    hoh: HOHService = Depends(get_hoh_service),
):
    data = await request.form()
    body = (data.get("Body") or "").strip()
    logger.info("Incoming WhatsApp body: %s", body)

    await hoh.handle_whatsapp_webhook(dict(data), org_id=1)
    return PlainTextResponse("OK")
