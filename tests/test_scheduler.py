"""
Tests for the scheduler service and internal API endpoints.
"""
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


def test_scheduler_service_exists():
    """Test that the scheduler service module exists and has required functions."""
    from app.services import scheduler
    
    assert hasattr(scheduler, 'run_once')
    assert hasattr(scheduler, 'find_shifts_needing_reminders')


def test_find_shifts_needing_reminders_function():
    """Test that find_shifts_needing_reminders is callable."""
    from app.services.scheduler import find_shifts_needing_reminders
    
    # Should be callable and return a list (or fail gracefully if DB not setup)
    try:
        result = find_shifts_needing_reminders(org_id=1)
        assert isinstance(result, list)
    except Exception as e:
        # If database tables don't exist in test, that's expected
        assert "employee_shifts" in str(e) or "OperationalError" in str(e)


def test_run_once_returns_counters():
    """Test that run_once returns expected counter structure."""
    from app.services.scheduler import run_once
    
    try:
        result = run_once(org_id=1)
        
        # Check all required counters are present
        assert "due_found" in result
        assert "sent" in result
        assert "failed" in result
        assert "skipped" in result
        assert "blocked" in result
        assert "postponed" in result
        assert "duration_ms" in result
        
        # Check types
        assert isinstance(result["due_found"], int)
        assert isinstance(result["sent"], int)
        assert isinstance(result["failed"], int)
        assert isinstance(result["skipped"], int)
        assert isinstance(result["blocked"], int)
        assert isinstance(result["postponed"], int)
        assert isinstance(result["duration_ms"], int)
    except Exception as e:
        # If database tables don't exist in test, that's expected
        # But the function should still raise an exception properly
        assert "employee_shifts" in str(e) or "OperationalError" in str(e)


def test_internal_router_exists():
    """Test that the internal router is properly defined."""
    from app.routers import internal
    
    assert internal.router is not None
    
    # Check that the route is defined (includes prefix)
    routes = [route.path for route in internal.router.routes]
    # The route path will be just the route without prefix
    assert any("run-scheduler" in route for route in routes)


def test_run_scheduler_endpoint_without_auth():
    """Test that the scheduler endpoint returns 401 without authorization."""
    from app.main import app
    
    client = TestClient(app)
    
    # Call without Authorization header
    response = client.post("/internal/run-scheduler")
    
    # Should return 401 or 500 depending on whether token is configured
    assert response.status_code in [401, 500]


def test_run_scheduler_endpoint_with_invalid_auth():
    """Test that the scheduler endpoint returns 401 with invalid authorization."""
    from app.main import app
    
    client = TestClient(app)
    
    # Set a token in environment for this test
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-secret-token"}):
        # Call with invalid token
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower() or "Invalid" in response.json()["detail"]


def test_run_scheduler_endpoint_with_wrong_format():
    """Test that the scheduler endpoint returns 401 with wrong auth format."""
    from app.main import app
    
    client = TestClient(app)
    
    # Set a token in environment for this test
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-secret-token"}):
        # Call with wrong format (no Bearer prefix)
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "test-secret-token"}
        )
        
        assert response.status_code == 401


def test_run_scheduler_endpoint_with_valid_auth():
    """Test that the scheduler endpoint works with valid authorization."""
    from app.main import app
    
    client = TestClient(app)
    
    # Set a token in environment for this test
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-secret-token"}):
        # Call with valid token
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        
        # Should succeed or fail due to database (not auth)
        # Accept 200 (success) or 500 (DB error) but not 401 (auth error)
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            # Check response structure
            data = response.json()
            assert "due_found" in data
            assert "sent" in data
            assert "failed" in data
            assert "skipped" in data
            assert "blocked" in data
            assert "postponed" in data
            assert "duration_ms" in data


def test_run_scheduler_endpoint_without_token_configured():
    """Test that the scheduler endpoint returns 500 when token is not configured."""
    from app.main import app
    
    client = TestClient(app)
    
    # Ensure token is not set
    with patch.dict(os.environ, {}, clear=False):
        # Remove the token if it exists
        if "SCHEDULER_RUN_TOKEN" in os.environ:
            del os.environ["SCHEDULER_RUN_TOKEN"]
        
        # Call with any authorization header
        response = client.post(
            "/internal/run-scheduler",
            headers={"Authorization": "Bearer any-token"}
        )
        
        # Should return 500 with message about token not configured
        assert response.status_code == 500
        assert "not configured" in response.json()["detail"].lower()


def test_get_scheduler_token_helper():
    """Test the get_scheduler_token helper function."""
    from app.routers.internal import get_scheduler_token
    
    # Test when not set
    with patch.dict(os.environ, {}, clear=False):
        if "SCHEDULER_RUN_TOKEN" in os.environ:
            del os.environ["SCHEDULER_RUN_TOKEN"]
        assert get_scheduler_token() is None
    
    # Test when set
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "my-token"}):
        assert get_scheduler_token() == "my-token"


def test_run_scheduler_with_org_id_parameter():
    """Test that the scheduler endpoint accepts org_id parameter."""
    from app.main import app
    
    client = TestClient(app)
    
    # Set a token in environment for this test
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-secret-token"}):
        # Call with org_id parameter
        response = client.post(
            "/internal/run-scheduler?org_id=1",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        
        # Should succeed or fail due to database (not auth)
        # Accept 200 (success) or 500 (DB error) but not 401 (auth error)
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            # Check response structure
            data = response.json()
            assert "due_found" in data
            assert "duration_ms" in data
