"""Health endpoint tests."""

from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == get_settings().bfa_service_slug
    assert isinstance(data["version"], str) and data["version"]
    assert isinstance(data["auth_test_mode"], bool)
