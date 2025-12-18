"""Tests for the new JacksonBot events API endpoints."""
import pytest
from datetime import date, datetime


def test_events_api_endpoints_exist():
    """Test that the API endpoints are properly defined."""
    from app.routers import events_api
    
    # Check that the router exists
    assert events_api.router is not None
    
    # Check that key routes are defined
    routes = [route.path for route in events_api.router.routes]
    
    assert "/events" in routes
    assert "/events/{event_id}" in routes
    assert "/events/{event_id}/technical-suggestions" in routes
    assert "/sse/events" in routes


def test_pubsub_singleton():
    """Test that pubsub returns the same instance."""
    from app.pubsub import get_pubsub
    
    pubsub1 = get_pubsub()
    pubsub2 = get_pubsub()
    
    assert pubsub1 is pubsub2, "get_pubsub should return singleton instance"


@pytest.mark.asyncio
async def test_pubsub_subscribe_unsubscribe():
    """Test basic pubsub functionality."""
    from app.pubsub import get_pubsub
    
    pubsub = get_pubsub()
    
    # Subscribe to a channel
    queue = await pubsub.subscribe("test_channel")
    assert queue is not None
    
    # Unsubscribe
    await pubsub.unsubscribe("test_channel", queue)


@pytest.mark.asyncio
async def test_pubsub_publish_message():
    """Test publishing and receiving messages."""
    from app.pubsub import get_pubsub
    import asyncio
    
    pubsub = get_pubsub()
    
    # Subscribe to a channel
    queue = await pubsub.subscribe("test_events")
    
    # Publish a message
    test_message = {"type": "test", "data": "hello"}
    await pubsub.publish("test_events", test_message)
    
    # Receive the message
    try:
        received = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert received == test_message
    finally:
        await pubsub.unsubscribe("test_events", queue)


def test_technical_suggestions_model():
    """Test the TechnicalSuggestion pydantic model."""
    from app.routers.events_api import TechnicalSuggestion
    
    suggestion = TechnicalSuggestion(
        contact_id=1,
        name="Test Technician",
        phone="+972501234567",
        last_event_name="Test Event",
        last_event_date="2024-01-15",
        times_worked=5
    )
    
    assert suggestion.contact_id == 1
    assert suggestion.name == "Test Technician"
    assert suggestion.times_worked == 5


def test_event_patch_request_model():
    """Test the EventPatchRequest pydantic model."""
    from app.routers.events_api import EventPatchRequest
    
    # Test with partial updates
    patch = EventPatchRequest(name="Updated Event", notes="New notes")
    assert patch.name == "Updated Event"
    assert patch.notes == "New notes"
    assert patch.event_date is None  # Not provided
    
    # Test with all fields
    patch_full = EventPatchRequest(
        name="Full Event",
        event_date="2024-12-25",
        show_time="20:00",
        load_in_time="18:00",
        producer_name="Producer Name",
        producer_phone="+972501234567",
        technical_name="Tech Name",
        technical_phone="+972509876543",
        notes="Full notes",
        status="confirmed"
    )
    assert patch_full.name == "Full Event"
    assert patch_full.status == "confirmed"
