"""Tests for the internal scheduler endpoint."""

import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


def test_internal_router_exists():
    """Test that the internal router is properly defined."""
    from app.routers import internal
    
    assert internal.router is not None
    
    # Check that the route is defined
    routes = [route.path for route in internal.router.routes]
    assert "/internal/run-scheduler" in routes


def test_get_scheduler_token():
    """Test the get_scheduler_token helper."""
    from app.utils.env import get_scheduler_token
    
    # Test when env var is set
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        token = get_scheduler_token()
        assert token == "test-token-123"
    
    # Test when env var is not set
    with patch.dict(os.environ, {}, clear=True):
        token = get_scheduler_token()
        assert token is None


def test_is_scheduler_token_configured():
    """Test the is_scheduler_token_configured helper."""
    from app.utils.env import is_scheduler_token_configured
    
    # Test when token is configured
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        assert is_scheduler_token_configured() is True
    
    # Test when token is not set
    with patch.dict(os.environ, {}, clear=True):
        assert is_scheduler_token_configured() is False
    
    # Test when token is empty
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": ""}):
        assert is_scheduler_token_configured() is False
    
    # Test when token is whitespace
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "   "}):
        assert is_scheduler_token_configured() is False


def test_verify_scheduler_token_not_configured():
    """Test authentication when token is not configured (should return 500)."""
    from app.main import app
    
    client = TestClient(app)
    
    # Clear the env var
    with patch.dict(os.environ, {}, clear=True):
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "Bearer some-token"}
        )
        
        assert response.status_code == 500
        assert "not configured" in response.json()["detail"].lower()


def test_verify_scheduler_token_missing_header():
    """Test authentication when Authorization header is missing (should return 401)."""
    from app.main import app
    
    client = TestClient(app)
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        response = client.post("/internal/run-scheduler")
        
        assert response.status_code == 401
        assert "authorization" in response.json()["detail"].lower()


def test_verify_scheduler_token_invalid_format():
    """Test authentication with invalid header format (should return 401)."""
    from app.main import app
    
    client = TestClient(app)
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        # Test without Bearer prefix
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "test-token-123"}
        )
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()
        
        # Test with wrong prefix
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "Basic test-token-123"}
        )
        assert response.status_code == 401


def test_verify_scheduler_token_wrong_token():
    """Test authentication with wrong token (should return 401)."""
    from app.main import app
    
    client = TestClient(app)
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "correct-token"}):
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "Bearer wrong-token"}
        )
        
        assert response.status_code == 401
        assert "invalid token" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_scheduler_endpoint_success():
    """Test successful scheduler run."""
    from app.main import app
    
    client = TestClient(app)
    
    # Mock the scheduler service
    mock_result = {
        "due_found": 5,
        "sent": 4,
        "failed": 0,
        "skipped": 1,
        "blocked": 0,
        "postponed": 0,
        "duration_ms": 1234,
    }
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        with patch("app.routers.internal.SchedulerService") as MockScheduler:
            # Setup mock
            mock_instance = MockScheduler.return_value
            mock_instance.run_once = AsyncMock(return_value=mock_result)
            
            # Make request
            response = client.post(
                "/internal/run-scheduler",
                headers={"Authorization": "Bearer test-token-123"}
            )
            
            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["due_found"] == 5
            assert data["sent"] == 4
            assert data["failed"] == 0
            assert data["skipped"] == 1
            assert data["blocked"] == 0
            assert data["postponed"] == 0
            assert data["duration_ms"] == 1234
            
            # Verify run_once was called with default org_id=None
            mock_instance.run_once.assert_called_once_with(org_id=None)


@pytest.mark.asyncio
async def test_run_scheduler_endpoint_with_org_id():
    """Test scheduler run with specific org_id."""
    from app.main import app
    
    client = TestClient(app)
    
    mock_result = {
        "due_found": 2,
        "sent": 2,
        "failed": 0,
        "skipped": 0,
        "blocked": 0,
        "postponed": 0,
        "duration_ms": 500,
    }
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        with patch("app.routers.internal.SchedulerService") as MockScheduler:
            mock_instance = MockScheduler.return_value
            mock_instance.run_once = AsyncMock(return_value=mock_result)
            
            # Make request with org_id
            response = client.post(
                "/internal/run-scheduler?org_id=42",
                headers={"Authorization": "Bearer test-token-123"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["due_found"] == 2
            assert data["sent"] == 2
            
            # Verify run_once was called with org_id=42
            mock_instance.run_once.assert_called_once_with(org_id=42)


def test_scheduler_service_initialization():
    """Test that SchedulerService can be initialized."""
    from app.services.scheduler import SchedulerService
    
    scheduler = SchedulerService()
    assert scheduler is not None
    assert scheduler.hoh is not None
    assert scheduler.orgs is not None
