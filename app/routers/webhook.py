from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService

router = APIRouter()


@router.post("/whatsapp-webhook")
async def whatsapp_webhook(
    request: Request,
    hoh: HOHService = Depends(get_hoh_service),
):
    data = await request.form()
    await hoh.handle_whatsapp_webhook(dict(data), org_id=1)
    return PlainTextResponse("OK")
