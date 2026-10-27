from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)


def test_health_check_healthy():
    """Verify health endpoint reports healthy when database is reachable."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "healthy"
    assert data["database"] == "connected"


def test_health_check_database_failure():
    """Verify health endpoint returns HTTP 503 and degraded status when database is unreachable."""
    with patch("app.routers.health.ping_database", return_value=False):
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["app"] == "healthy"
        assert data["database"] == "disconnected"
