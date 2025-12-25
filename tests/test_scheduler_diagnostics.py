"""Tests for scheduler diagnostics endpoint."""

import os
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_diagnostics_endpoint_requires_auth():
    """Test that diagnostics endpoint requires authentication."""
    from app.main import app
    
    client = TestClient(app)
    
    # Test without Authorization header
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        response = client.get("/internal/diagnostics/scheduler")
        assert response.status_code == 401
        assert "authorization" in response.json()["detail"].lower()


def test_diagnostics_endpoint_rejects_invalid_token():
    """Test that diagnostics endpoint rejects invalid tokens."""
    from app.main import app
    
    client = TestClient(app)
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "correct-token"}):
        response = client.get(
            "/internal/diagnostics/scheduler",
            headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401
        assert "invalid token" in response.json()["detail"].lower()


def test_diagnostics_endpoint_requires_configured_token():
    """Test that diagnostics endpoint returns 500 if token not configured."""
    from app.main import app
    
    client = TestClient(app)
    
    with patch.dict(os.environ, {}, clear=True):
        response = client.get(
            "/internal/diagnostics/scheduler",
            headers={"Authorization": "Bearer some-token"}
        )
        assert response.status_code == 500
        assert "not configured" in response.json()["detail"].lower()


def test_diagnostics_endpoint_returns_json_structure():
    """Test that diagnostics endpoint returns expected JSON structure."""
    from app.main import app
    
    client = TestClient(app)
    
    # Mock the diagnostics function to avoid actual DB calls
    mock_report = {
        "summary": {
            "suspected_root_cause": "Test cause",
            "confidence": 80,
            "key_evidence": ["Evidence 1", "Evidence 2"],
            "checks_summary": {
                "total": 7,
                "passed": 5,
                "warnings": 2,
                "failed": 0
            }
        },
        "checks": [
            {
                "name": "DB_FINGERPRINT",
                "status": "pass",
                "details": {},
                "why_it_matters": "Test",
                "likely_root_cause": None,
                "next_actions": []
            }
        ],
        "recommendations": [
            {
                "priority": "P1",
                "title": "Test recommendation",
                "description": "Test description",
                "commands": []
            }
        ]
    }
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        with patch("app.routers.internal.run_scheduler_diagnostics") as mock_diag:
            mock_diag.return_value = mock_report
            
            response = client.get(
                "/internal/diagnostics/scheduler",
                headers={"Authorization": "Bearer test-token-123"}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify top-level keys
            assert "summary" in data
            assert "checks" in data
            assert "recommendations" in data
            
            # Verify summary structure
            assert "suspected_root_cause" in data["summary"]
            assert "confidence" in data["summary"]
            assert "key_evidence" in data["summary"]
            assert "checks_summary" in data["summary"]
            
            # Verify checks is a list
            assert isinstance(data["checks"], list)
            assert len(data["checks"]) > 0
            
            # Verify recommendations is a list
            assert isinstance(data["recommendations"], list)
            assert len(data["recommendations"]) > 0


def test_diagnostics_endpoint_with_org_id():
    """Test that diagnostics endpoint accepts org_id parameter."""
    from app.main import app
    
    client = TestClient(app)
    
    mock_report = {
        "summary": {
            "suspected_root_cause": "Test",
            "confidence": 50,
            "key_evidence": [],
            "checks_summary": {"total": 1, "passed": 1, "warnings": 0, "failed": 0}
        },
        "checks": [],
        "recommendations": []
    }
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        with patch("app.routers.internal.run_scheduler_diagnostics") as mock_diag:
            mock_diag.return_value = mock_report
            
            response = client.get(
                "/internal/diagnostics/scheduler?org_id=42",
                headers={"Authorization": "Bearer test-token-123"}
            )
            
            assert response.status_code == 200
            
            # Verify org_id was passed to diagnostics function
            mock_diag.assert_called_once_with(org_id=42)


def test_diagnostics_endpoint_handles_errors():
    """Test that diagnostics endpoint handles execution errors gracefully."""
    from app.main import app
    
    client = TestClient(app)
    
    with patch.dict(os.environ, {"SCHEDULER_RUN_TOKEN": "test-token-123"}):
        with patch("app.routers.internal.run_scheduler_diagnostics") as mock_diag:
            mock_diag.side_effect = Exception("Database connection failed")
            
            response = client.get(
                "/internal/diagnostics/scheduler",
                headers={"Authorization": "Bearer test-token-123"}
            )
            
            assert response.status_code == 500
            assert "failed" in response.json()["detail"].lower()


def test_diagnostics_route_exists():
    """Test that the diagnostics route is properly registered."""
    from app.routers import internal
    
    routes = [route.path for route in internal.router.routes]
    assert "/internal/diagnostics/scheduler" in routes


def test_run_scheduler_diagnostics_basic():
    """Test that run_scheduler_diagnostics can be imported and returns expected structure."""
    from app.diagnostics.scheduler import run_scheduler_diagnostics
    
    # This test just verifies the function exists and has the right signature
    # We won't run it against a real DB in tests
    assert callable(run_scheduler_diagnostics)


def test_check_functions_exist():
    """Test that all diagnostic check functions exist."""
    from app.diagnostics import scheduler as diag_module
    
    # Verify check functions exist
    assert hasattr(diag_module, "check_database_fingerprint")
    assert hasattr(diag_module, "check_schema_existence")
    assert hasattr(diag_module, "check_scheduled_messages_data")
    assert hasattr(diag_module, "check_org_scoping")
    assert hasattr(diag_module, "simulate_endpoint_queries")
    assert hasattr(diag_module, "check_fetch_diagnostics")
    assert hasattr(diag_module, "check_timezone_sanity")
    assert hasattr(diag_module, "compute_summary")
    assert hasattr(diag_module, "generate_recommendations")
