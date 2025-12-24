"""Notifications API for real-time message alerts."""
import json
import logging
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.repositories import MessageRepository
from app.pubsub import get_pubsub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_message_repo() -> MessageRepository:
    """Dependency for message repository."""
    return MessageRepository()


@router.get("/summary")
def get_notifications_summary(
    org_id: int = Query(1),
    user_id: str = Query("admin"),
    limit: int = Query(5, ge=1, le=20),
    message_repo: MessageRepository = Depends(get_message_repo),
):
    """
    Get notification summary with unread count and recent events.
    
    Returns:
        - unread_count_total: Total number of unread messages
        - items: List of up to `limit` events with new messages, each containing:
            - event_id
            - event_name
            - event_date
            - hall_id
            - hall_name
            - last_message_snippet
            - last_message_at
            - unread_count_for_event
    """
    return message_repo.get_unread_summary(org_id, user_id, limit)


@router.get("/messages")
def get_recent_messages(
    org_id: int = Query(1),
    limit: int = Query(200, ge=1, le=500),
    message_repo: MessageRepository = Depends(get_message_repo),
):
    """
    Get recent messages with event details.
    
    Args:
        org_id: Organization ID
        limit: Maximum number of messages to return
    
    Returns:
        List of messages with event information
    """
    messages = message_repo.get_recent_messages_with_events(org_id, limit)
    return {"messages": messages}


@router.post("/mark-all-read")
def mark_all_as_read(
    org_id: int = Query(1),
    user_id: str = Query("admin"),
    message_repo: MessageRepository = Depends(get_message_repo),
):
    """
    Mark all messages as read for the current user.
    Updates the user's last_seen state without deleting any messages.
    """
    message_repo.mark_all_as_read(org_id, user_id)
    return {"success": True}


@router.post("/clear")
def clear_notifications(
    org_id: int = Query(1),
    user_id: str = Query("admin"),
    message_repo: MessageRepository = Depends(get_message_repo),
):
    """
    Clear notifications by marking all as read.
    This is an alias for mark-all-read - it does NOT delete messages.
    """
    message_repo.mark_all_as_read(org_id, user_id)
    return {"success": True}


@router.get("/sse")
async def sse_notifications(org_id: int = Query(1)):
    """
    Server-Sent Events endpoint for real-time notification updates.
    Clients connect here to receive live updates when new messages arrive.
    
    Events:
        - connected: Initial connection confirmation
        - incoming_message: New incoming message with event details
    """
    async def event_generator():
        pubsub = get_pubsub()
        queue = await pubsub.subscribe("notifications")
        
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
                    
                    # Filter by org_id if specified in message
                    if message.get("org_id") and message["org_id"] != org_id:
                        continue
                    
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
            logger.info("Notification SSE connection cancelled")
        except Exception as e:
            logger.error(f"Error in notification SSE: {e}")
        finally:
            await pubsub.unsubscribe("notifications", queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering in nginx
        },
    )
