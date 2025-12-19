"""
API endpoints for the JacksonBot events redesign.
Provides RESTful API for event management, inline editing, and technical suggestions.
"""
import asyncio
import json
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import get_hoh_service
from app.hoh_service import HOHService
from app.pubsub import get_pubsub
from app.time_utils import (
    utc_to_local_time_str,
    utc_to_local_date_str,
    format_datetime_for_display,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["events-api"])


# --- Pydantic Models ---

class EventPatchRequest(BaseModel):
    """Request model for patching an event. Only include fields you want to update."""
    name: Optional[str] = None
    event_date: Optional[str] = None  # YYYY-MM-DD
    show_time: Optional[str] = None  # HH:MM
    load_in_time: Optional[str] = None  # HH:MM
    producer_name: Optional[str] = None
    producer_phone: Optional[str] = None
    producer_contact_id: Optional[int] = None
    technical_name: Optional[str] = None
    technical_phone: Optional[str] = None
    technical_contact_id: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class TechnicalSuggestion(BaseModel):
    """A suggested technical contact based on producer history."""
    contact_id: int
    name: str
    phone: str
    last_event_name: Optional[str] = None
    last_event_date: Optional[str] = None
    times_worked: int


# --- Endpoints ---

@router.get("/events")
async def list_events(
    month: str = Query(..., description="Month in YYYY-MM format"),
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    List events for a specific month with full details.
    Returns events grouped data including hall information.
    """
    try:
        # Parse month
        year, month_num = map(int, month.split("-"))
        
        # Get all events for the org
        all_events = hoh.list_events_for_org(org_id=org_id)
        
        # Filter by month
        filtered_events = []
        for event in all_events:
            event_date = event.get("event_date")
            if event_date and event_date.year == year and event_date.month == month_num:
                filtered_events.append(event)
        
        # Group by hall
        halls: Dict[str, List[Dict]] = {}
        for event in filtered_events:
            hall_name = event.get("hall_name") or f"Hall #{event.get('hall_id', 'Unknown')}"
            if hall_name not in halls:
                halls[hall_name] = []
            # Format times for display (Israel timezone)
            show_time_utc = event.get("show_time")
            load_in_time_utc = event.get("load_in_time")
            init_sent_at_utc = event.get("init_sent_at")
            
            halls[hall_name].append({
                "event_id": event.get("event_id"),
                "name": event.get("name"),
                "event_date": event.get("event_date").isoformat() if event.get("event_date") else None,
                "show_time": show_time_utc.isoformat() if show_time_utc else None,
                "show_time_display": utc_to_local_time_str(show_time_utc) if show_time_utc else "",
                "load_in_time": load_in_time_utc.isoformat() if load_in_time_utc else None,
                "load_in_time_display": utc_to_local_time_str(load_in_time_utc) if load_in_time_utc else "",
                "status": event.get("status"),
                "notes": event.get("notes"),
                "producer_name": event.get("producer_name"),
                "producer_phone": event.get("producer_phone"),
                "technical_name": event.get("technical_name"),
                "technical_phone": event.get("technical_phone"),
                "technical_contact_id": event.get("technical_contact_id"),
                "producer_contact_id": event.get("producer_contact_id"),
                "latest_delivery_status": event.get("latest_delivery_status"),
                "init_sent_at": init_sent_at_utc.isoformat() if init_sent_at_utc else None,
                "init_sent_at_display": format_datetime_for_display(init_sent_at_utc) if init_sent_at_utc else "",
            })
        
        return {
            "month": month,
            "halls": halls,
            "total_events": len(filtered_events),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid month format: {e}")
    except Exception as e:
        logger.exception("Failed to list events")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/events/{event_id}")
async def update_event(
    event_id: int,
    updates: EventPatchRequest,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Update specific fields of an event (inline edit).
    Only provided fields will be updated. Validates business rules.
    """
    try:
        # Get current event to validate
        event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Build update parameters - only include non-None values
        update_params = {}
        if updates.name is not None:
            update_params["event_name"] = updates.name
        if updates.event_date is not None:
            update_params["event_date_str"] = updates.event_date
        if updates.show_time is not None:
            update_params["show_time_str"] = updates.show_time
        if updates.load_in_time is not None:
            update_params["load_in_time_str"] = updates.load_in_time
        if updates.producer_name is not None:
            update_params["producer_name"] = updates.producer_name
        if updates.producer_phone is not None:
            update_params["producer_phone"] = updates.producer_phone
        if updates.producer_contact_id is not None:
            update_params["producer_contact_id"] = updates.producer_contact_id
        if updates.technical_name is not None:
            update_params["technical_name"] = updates.technical_name
        if updates.technical_phone is not None:
            update_params["technical_phone"] = updates.technical_phone
        if updates.technical_contact_id is not None:
            update_params["technical_contact_id"] = updates.technical_contact_id
        if updates.notes is not None:
            update_params["notes"] = updates.notes
        
        # Use existing service method which has all the validation
        hoh.update_event_with_contacts(
            org_id=org_id,
            event_id=event_id,
            **update_params
        )
        
        # Broadcast update via SSE
        pubsub = get_pubsub()
        await pubsub.publish("events", {
            "type": "event_updated",
            "event_id": event_id,
            "org_id": org_id,
        })
        
        # Return updated event with formatted display fields
        updated_event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        
        # Format times for display (Israel timezone)
        show_time_utc = updated_event.get("show_time")
        load_in_time_utc = updated_event.get("load_in_time")
        init_sent_at_utc = updated_event.get("init_sent_at")
        
        return {
            "success": True,
            "event_id": event_id,
            "event": {
                **updated_event,
                "event_date": updated_event.get("event_date").isoformat() if updated_event.get("event_date") else None,
                "show_time": show_time_utc.isoformat() if show_time_utc else None,
                "show_time_display": utc_to_local_time_str(show_time_utc) if show_time_utc else "",
                "load_in_time": load_in_time_utc.isoformat() if load_in_time_utc else None,
                "load_in_time_display": utc_to_local_time_str(load_in_time_utc) if load_in_time_utc else "",
                "init_sent_at": init_sent_at_utc.isoformat() if init_sent_at_utc else None,
                "init_sent_at_display": format_datetime_for_display(init_sent_at_utc) if init_sent_at_utc else "",
            },
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update event {event_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events/{event_id}/technical-suggestions")
async def get_technical_suggestions(
    event_id: int,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
) -> List[TechnicalSuggestion]:
    """
    Get suggested technical contacts based on producer history.
    Returns contacts who have worked with the same producer before.
    """
    try:
        # Get current event
        event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        producer_contact_id = event.get("producer_contact_id")
        if not producer_contact_id:
            # No producer, no suggestions
            return []
        
        # Query for technical contacts who worked with this producer before
        suggestions = hoh.get_technical_suggestions_for_producer(
            org_id=org_id,
            producer_contact_id=producer_contact_id,
        )
        
        return [
            TechnicalSuggestion(
                contact_id=s["contact_id"],
                name=s["name"],
                phone=s["phone"],
                last_event_name=s.get("last_event_name"),
                last_event_date=s.get("last_event_date").isoformat() if s.get("last_event_date") else None,
                times_worked=s["times_worked"],
            )
            for s in suggestions
        ]
    
    except Exception as e:
        logger.exception(f"Failed to get technical suggestions for event {event_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Delete an event (PHASE 3 - Task 5A).
    """
    try:
        # Check if event exists
        event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Delete the event
        hoh.delete_event(org_id=org_id, event_id=event_id)
        
        # Broadcast deletion via SSE
        pubsub = get_pubsub()
        await pubsub.publish("events", {
            "type": "event_deleted",
            "event_id": event_id,
            "org_id": org_id,
        })
        
        return {"success": True, "message": "Event deleted successfully"}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to delete event {event_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events/{event_id}/send-whatsapp")
async def send_whatsapp_for_event(
    event_id: int,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Send WhatsApp INIT message for an event (PHASE 3 - Task 5B).
    """
    try:
        # Check if event exists
        event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Send INIT message
        await hoh.send_init_for_event(org_id=org_id, event_id=event_id)
        
        return {"success": True, "message": "WhatsApp message sent successfully"}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to send WhatsApp for event {event_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events/{event_id}/shifts")
async def list_shifts_for_event(
    event_id: int,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Get all shifts for an event (PHASE 4 - Task 7).
    """
    try:
        # Check if event exists
        event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Get shifts from repository
        shifts = hoh.employee_shifts.list_shifts_for_event(org_id=org_id, event_id=event_id)
        
        # Format shifts for response
        result = []
        for shift in shifts:
            call_time_utc = shift.get("call_time")
            reminder_sent_utc = shift.get("reminder_24h_sent_at")
            
            result.append({
                "shift_id": shift["shift_id"],
                "employee_id": shift["employee_id"],
                "employee_name": shift.get("employee_name"),
                "employee_phone": shift.get("employee_phone"),
                "call_time": call_time_utc.isoformat() if call_time_utc else None,
                "call_time_display": format_datetime_for_display(call_time_utc, include_date=False) if call_time_utc else "",
                "call_date_display": utc_to_local_date_str(call_time_utc, format="%Y-%m-%d") if call_time_utc else "",
                "shift_role": shift.get("shift_role"),
                "notes": shift.get("notes"),
                "reminder_24h_sent_at": reminder_sent_utc.isoformat() if reminder_sent_utc else None,
                "reminder_sent_display": format_datetime_for_display(reminder_sent_utc) if reminder_sent_utc else "",
            })
        
        return {"shifts": result}
    
    except Exception as e:
        logger.exception(f"Failed to list shifts for event {event_id}")
        raise HTTPException(status_code=500, detail=str(e))


class ShiftCreateRequest(BaseModel):
    """Request model for creating a shift."""
    employee_name: str = Field(..., description="Employee name")
    shift_date: Optional[str] = Field(None, description="Shift date (YYYY-MM-DD)")
    shift_time: Optional[str] = Field(None, description="Shift time (HH:MM)")
    notes: Optional[str] = None


@router.post("/events/{event_id}/shifts")
async def create_shift_for_event(
    event_id: int,
    shift_data: ShiftCreateRequest,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Create a new shift for an event (PHASE 4 - Task 7).
    """
    try:
        from app.time_utils import parse_local_time_to_utc
        from datetime import datetime, date as date_type
        
        # Check if event exists
        event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Find or create employee by name
        # First try to find existing employee
        employees = hoh.employees.list_employees(org_id=org_id)
        employee = next((e for e in employees if e["name"] == shift_data.employee_name), None)
        
        if not employee:
            # Create new employee with placeholder phone
            employee_id = hoh.employees.create_employee(
                org_id=org_id,
                name=shift_data.employee_name,
                phone="",  # Empty string as placeholder (can be updated later)
            )
        else:
            employee_id = employee["employee_id"]
        
        # Determine call_time
        # Default to event's date and load_in_time
        shift_date = shift_data.shift_date or (event["event_date"].isoformat() if event.get("event_date") else None)
        shift_time = shift_data.shift_time
        
        if not shift_time and event.get("load_in_time"):
            # Extract time from load_in_time
            shift_time = event["load_in_time"].strftime("%H:%M")
        elif not shift_time:
            shift_time = "09:00"  # Default fallback
        
        if not shift_date:
            raise HTTPException(status_code=400, detail="Shift date is required")
        
        # Parse to UTC datetime
        call_time_utc = parse_local_time_to_utc(date_type.fromisoformat(shift_date), shift_time)
        
        # Create shift
        shift_id = hoh.employee_shifts.create_shift(
            org_id=org_id,
            event_id=event_id,
            employee_id=employee_id,
            call_time=call_time_utc,
            shift_role=None,
            notes=shift_data.notes,
        )
        
        return {
            "success": True,
            "shift_id": shift_id,
            "employee_id": employee_id,
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create shift for event {event_id}")
        raise HTTPException(status_code=500, detail=str(e))


class ShiftPatchRequest(BaseModel):
    """Request model for updating a shift."""
    employee_id: Optional[int] = None  # Direct employee ID (from dropdown)
    employee_name: Optional[str] = None  # Legacy text input
    shift_date: Optional[str] = None  # YYYY-MM-DD
    shift_time: Optional[str] = None  # HH:MM
    notes: Optional[str] = None


@router.patch("/shifts/{shift_id}")
async def update_shift(
    shift_id: int,
    updates: ShiftPatchRequest,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Update a shift (PHASE 4 - Task 7).
    """
    try:
        from app.time_utils import parse_local_time_to_utc, utc_to_local_datetime
        from datetime import date as date_type
        
        # Get current shift
        shift = hoh.employee_shifts.get_shift_by_id(org_id=org_id, shift_id=shift_id)
        if not shift:
            raise HTTPException(status_code=404, detail="Shift not found")
        
        # Build update parameters
        update_params = {}
        
        # Handle employee change (PHASE 5: prefer employee_id from dropdown)
        if updates.employee_id is not None:
            # Direct employee ID provided from dropdown
            update_params["employee_id"] = updates.employee_id
        elif updates.employee_name is not None:
            # Legacy: Find or create employee by name
            employees = hoh.employees.list_employees(org_id=org_id)
            employee = next((e for e in employees if e["name"] == updates.employee_name), None)
            
            if not employee:
                # Create new employee with placeholder phone
                employee_id = hoh.employees.create_employee(
                    org_id=org_id,
                    name=updates.employee_name,
                    phone="",  # Empty string as placeholder
                )
                update_params["employee_id"] = employee_id
            else:
                update_params["employee_id"] = employee["employee_id"]
        
        # Handle date/time changes
        if updates.shift_date is not None or updates.shift_time is not None:
            # Get current call_time
            current_call_time = shift["call_time"]
            local_dt = utc_to_local_datetime(current_call_time) if current_call_time else None
            
            # Determine new date and time
            if updates.shift_date:
                new_date = date_type.fromisoformat(updates.shift_date)
            else:
                new_date = local_dt.date() if local_dt else date_type.today()
            
            if updates.shift_time:
                new_time = updates.shift_time
            else:
                new_time = local_dt.strftime("%H:%M") if local_dt else "09:00"
            
            # Convert to UTC
            new_call_time = parse_local_time_to_utc(new_date, new_time)
            update_params["call_time"] = new_call_time
        
        # Handle notes
        if updates.notes is not None:
            update_params["notes"] = updates.notes
        
        # Update shift
        if update_params:
            hoh.employee_shifts.update_shift(org_id=org_id, shift_id=shift_id, **update_params)
        
        return {"success": True, "shift_id": shift_id}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update shift {shift_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/shifts/{shift_id}")
async def delete_shift(
    shift_id: int,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Delete a shift (PHASE 4 - Task 7).
    """
    try:
        # Check if shift exists
        shift = hoh.employee_shifts.get_shift_by_id(org_id=org_id, shift_id=shift_id)
        if not shift:
            raise HTTPException(status_code=404, detail="Shift not found")
        
        # Delete shift
        hoh.employee_shifts.delete_shift(org_id=org_id, shift_id=shift_id)
        
        return {"success": True, "message": "Shift deleted successfully"}
    
    except Exception as e:
        logger.exception(f"Failed to delete shift {shift_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/shifts/{shift_id}/send-reminder")
async def send_shift_reminder(
    shift_id: int,
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Send WhatsApp reminder for a shift (PHASE 4 - Task 7).
    """
    try:
        from app.time_utils import utc_to_local_datetime, format_datetime_for_display
        from app.credentials import CONTENT_SID_SHIFT_REMINDER
        from app import twilio_client
        
        # Get shift with employee details
        shift = hoh.employee_shifts.get_shift_by_id(org_id=org_id, shift_id=shift_id)
        if not shift:
            raise HTTPException(status_code=404, detail="Shift not found")
        
        employee_phone = shift.get("employee_phone")
        if not employee_phone or employee_phone.strip() == "":
            raise HTTPException(
                status_code=400, 
                detail="Employee has no phone number. Please add a phone number before sending reminders."
            )
        
        # Get event details
        event = hoh.get_event_with_contacts(org_id=org_id, event_id=shift["event_id"])
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Format times for message
        call_time_local = utc_to_local_datetime(shift["call_time"])
        event_date_str = format_datetime_for_display(call_time_local)
        
        # Send WhatsApp reminder
        if CONTENT_SID_SHIFT_REMINDER:
            twilio_client.send_whatsapp_template(
                to_phone=employee_phone,
                content_sid=CONTENT_SID_SHIFT_REMINDER,
                content_variables={
                    "1": shift.get("employee_name", "Employee"),
                    "2": event.get("name", "Event"),
                    "3": event_date_str,
                }
            )
        else:
            logger.warning("CONTENT_SID_SHIFT_REMINDER not configured, skipping WhatsApp send")
        
        # Mark reminder as sent
        hoh.employee_shifts.mark_24h_reminder_sent(shift_id=shift_id)
        
        return {"success": True, "message": "Reminder sent successfully"}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to send reminder for shift {shift_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sse/events")
async def sse_events(org_id: int = Query(1)):
    """
    Server-Sent Events endpoint for real-time event updates.
    Clients connect here to receive live updates when events change.
    """
    async def event_generator():
        pubsub = get_pubsub()
        queue = await pubsub.subscribe("events")
        
        try:
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'org_id': org_id})}\n\n"
            
            # Heartbeat counter
            last_heartbeat = asyncio.get_event_loop().time()
            heartbeat_interval = 20  # seconds
            
            while True:
                try:
                    # Wait for message with timeout for heartbeat
                    message = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    
                    # Send the message
                    yield f"data: {json.dumps(message)}\n\n"
                    last_heartbeat = asyncio.get_event_loop().time()
                    
                except asyncio.TimeoutError:
                    # Send heartbeat
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat >= heartbeat_interval:
                        yield f": heartbeat\n\n"
                        last_heartbeat = current_time
                
        except asyncio.CancelledError:
            logger.info("SSE connection cancelled")
        except Exception as e:
            logger.error(f"SSE error: {e}")
        finally:
            await pubsub.unsubscribe("events", queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering in nginx
        },
    )


@router.get("/contacts/by-role")
async def get_contacts_by_role(
    role: Optional[str] = Query(None, description="Filter by role (e.g., 'מפיק', 'טכני')"),
    search: Optional[str] = Query(None, description="Search by name or phone"),
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Get contacts filtered by role and/or search term (PHASE 4).
    Returns contacts with name, phone, and role.
    """
    try:
        # Get all contacts by role
        contacts_by_role = hoh.list_contacts_by_role(org_id=org_id)
        
        # If role filter is specified, only return that role
        if role:
            contacts = contacts_by_role.get(role, [])
        else:
            # Return all contacts
            contacts = []
            for role_contacts in contacts_by_role.values():
                contacts.extend(role_contacts)
        
        # Apply search filter if provided
        if search:
            search_lower = search.lower()
            contacts = [
                c for c in contacts
                if (search_lower in (c.get("name") or "").lower() or
                    search_lower in (c.get("phone") or ""))
            ]
        
        # Format response
        return {
            "contacts": [
                {
                    "contact_id": c.get("contact_id"),
                    "name": c.get("name"),
                    "phone": c.get("phone"),
                    "role": c.get("role"),
                }
                for c in contacts
            ]
        }
    
    except Exception as e:
        logger.exception("Failed to get contacts by role")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employees")
async def get_employees(
    search: Optional[str] = Query(None, description="Search by name"),
    active_only: bool = Query(True, description="Only return active employees"),
    org_id: int = Query(1),
    hoh: HOHService = Depends(get_hoh_service),
):
    """
    Get employees for dropdown selection (PHASE 5).
    Returns employees with name only (as per spec: "שם בלבד").
    """
    try:
        # Get all employees
        employees = hoh.list_employees(org_id=org_id, active_only=active_only)
        
        # Apply search filter if provided
        if search:
            search_lower = search.lower()
            employees = [
                e for e in employees
                if search_lower in (e.get("name") or "").lower()
            ]
        
        # Format response - name only as per spec
        return {
            "employees": [
                {
                    "employee_id": e.get("employee_id"),
                    "name": e.get("name"),
                }
                for e in employees
            ]
        }
    
    except Exception as e:
        logger.exception("Failed to get employees")
        raise HTTPException(status_code=500, detail=str(e))
