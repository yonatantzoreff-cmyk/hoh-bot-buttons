"""API routes for calendar import feature.

Note: org_id is hard-coded to 1 throughout this router, consistent with the rest
of the application (see app/routers/ui.py). Multi-org authentication will be 
implemented in a future update.
"""

import logging
from datetime import date, time
from typing import Any, Dict, List, Optional

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.db_schema import SchemaMissingError, database_label
from app.services.calendar_import_service import CalendarImportService

router = APIRouter(prefix="/import", tags=["calendar_import"])
logger = logging.getLogger(__name__)

# Pydantic models for request/response


class UploadResponse(BaseModel):
    job_id: int
    status: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_warnings: List[Dict[str, Any]]


class StagingEventResponse(BaseModel):
    id: int
    row_index: int
    date: Optional[date]
    show_time: Optional[time]
    name: Optional[str]
    load_in: Optional[time]
    event_series: Optional[str]
    producer_name: Optional[str]
    producer_phone: Optional[str]
    notes: Optional[str]
    is_valid: bool
    errors: List[str]
    warnings: List[str]


class UpdateStagingEventRequest(BaseModel):
    date: Optional[date] = None
    show_time: Optional[time] = None
    name: Optional[str] = None
    load_in: Optional[time] = None
    event_series: Optional[str] = None
    producer_name: Optional[str] = None
    producer_phone: Optional[str] = None
    notes: Optional[str] = None


class ValidationResponse(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_warnings: List[Dict[str, Any]]


class CommitResponse(BaseModel):
    status: str
    committed_count: int
    error_count: int
    errors: List[Dict[str, Any]]
    skipped_duplicates: int


# Service instance
def get_import_service():
    return CalendarImportService()


@router.post("/upload", response_model=UploadResponse)
async def upload_excel(
    file: UploadFile = File(...),
    org_id: int = Form(1),  # TODO: Get from auth context when multi-org auth is implemented
):
    """
    Upload an Excel file for calendar import.
    
    This clears existing staging data, parses the Excel file,
    validates all rows, and returns a summary.
    """
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400, detail="Invalid file format. Only .xlsx files are supported."
        )

    try:
        content = await file.read()
        service = get_import_service()
        result = service.upload_and_parse(
            org_id=org_id, file_content=content, filename=file.filename
        )
        return result
    except SchemaMissingError as e:
        logger.error("Calendar upload failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail="Upload failed")


@router.get("/staging", response_model=List[StagingEventResponse])
async def list_staging_events(
    org_id: int = 1,  # TODO: Get from auth context
):
    """
    List all staging events.
    """
    service = get_import_service()
    try:
        events = service.list_staging_events(org_id)
        return events
    except SchemaMissingError as e:
        logger.error("List staging events failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/staging/{staging_id}", response_model=StagingEventResponse)
async def update_staging_event(
    staging_id: int,
    updates: UpdateStagingEventRequest,
    org_id: int = 1,  # TODO: Get from auth context
):
    """
    Update a single staging event field(s) and revalidate.
    """
    service = get_import_service()

    # Only include non-None fields
    fields = {k: v for k, v in updates.dict().items() if v is not None}

    try:
        result = service.update_staging_event(org_id, staging_id, fields)
        return result
    except SchemaMissingError as e:
        logger.error("Update staging event failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Update failed")
        raise HTTPException(status_code=500, detail="Update failed")


@router.post("/staging", response_model=StagingEventResponse)
async def add_staging_event(
    org_id: int = 1,  # TODO: Get from auth context
):
    """
    Add a new blank staging event row.
    """
    service = get_import_service()
    try:
        result = service.add_staging_event(org_id)
        return result
    except SchemaMissingError as e:
        logger.error("Add staging event failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/staging/{staging_id}")
async def delete_staging_event(
    staging_id: int,
    org_id: int = 1,  # TODO: Get from auth context
):
    """
    Delete a staging event.
    """
    service = get_import_service()
    try:
        service.delete_staging_event(org_id, staging_id)
        return {"status": "deleted"}
    except SchemaMissingError as e:
        logger.error("Delete staging event failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Delete failed")
        raise HTTPException(status_code=500, detail="Delete failed")


@router.post("/validate", response_model=ValidationResponse)
async def validate_all(
    org_id: int = 1,  # TODO: Get from auth context
):
    """
    Revalidate all staging events and check for duplicates.
    """
    service = get_import_service()
    try:
        result = service.revalidate_all(org_id)
        return result
    except SchemaMissingError as e:
        logger.error("Validation failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/commit", response_model=CommitResponse)
async def commit_to_events(
    skip_duplicates: bool = Form(False),
    org_id: int = Form(1),  # TODO: Get from auth context
):
    """
    Commit valid staging events to official events table.
    
    This creates events and contacts as needed, then clears all staging data.
    Uses a single transaction - if any failure occurs, all changes are rolled back.
    """
    service = get_import_service()
    try:
        result = service.commit_to_events(org_id, skip_duplicates)
        return result
    except SchemaMissingError as e:
        logger.error("Commit failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Commit failed")
        raise HTTPException(status_code=500, detail="Commit failed")


@router.post("/clear")
async def clear_staging(
    org_id: int = 1,  # TODO: Get from auth context
):
    """
    Clear all staging events immediately.
    """
    service = get_import_service()
    try:
        service.clear_all_staging(org_id)
        return {"status": "cleared"}
    except SchemaMissingError as e:
        logger.error("Clear staging failed; %s (DB: %s)", e, database_label())
        raise HTTPException(status_code=500, detail=str(e))
