# app/routers/followups.py
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService


router = APIRouter()


@router.post("/run_followups")
async def run_followups(hoh: HOHService = Depends(get_hoh_service)):
    count = await hoh.run_due_followups(org_id=1)
    return JSONResponse({"processed": count})
