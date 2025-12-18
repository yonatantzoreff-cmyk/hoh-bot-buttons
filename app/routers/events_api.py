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
    technical_name: Optional[str] = None
    technical_phone: Optional[str] = None
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
            halls[hall_name].append({
                "event_id": event.get("event_id"),
                "name": event.get("name"),
                "event_date": event.get("event_date").isoformat() if event.get("event_date") else None,
                "show_time": event.get("show_time").isoformat() if event.get("show_time") else None,
                "load_in_time": event.get("load_in_time").isoformat() if event.get("load_in_time") else None,
                "status": event.get("status"),
                "notes": event.get("notes"),
                "producer_name": event.get("producer_name"),
                "producer_phone": event.get("producer_phone"),
                "technical_name": event.get("technical_name"),
                "technical_phone": event.get("technical_phone"),
                "technical_contact_id": event.get("technical_contact_id"),
                "producer_contact_id": event.get("producer_contact_id"),
                "latest_delivery_status": event.get("latest_delivery_status"),
                "init_sent_at": event.get("init_sent_at").isoformat() if event.get("init_sent_at") else None,
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
        if updates.technical_name is not None:
            update_params["technical_name"] = updates.technical_name
        if updates.technical_phone is not None:
            update_params["technical_phone"] = updates.technical_phone
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
        
        # Return updated event
        updated_event = hoh.get_event_with_contacts(org_id=org_id, event_id=event_id)
        return {
            "success": True,
            "event_id": event_id,
            "event": updated_event,
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
