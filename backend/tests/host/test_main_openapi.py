"""OpenAPI and main app tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app


def test_custom_openapi_security_annotations() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert app.openapi() is schema
    health_get = schema["paths"]["/health"]["get"]
    assert health_get.get("security") == []
    ready_get = schema["paths"]["/health/ready"]["get"]
    assert ready_get.get("security") == [{"HTTPBearer": []}]


def test_openapi_invoke_request_includes_confirm_phase_fields() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    invoke_body = schema["components"]["schemas"]["BfaInvokeRequest"]["properties"]
    assert "invoke_phase" in invoke_body
    assert "plan_token" in invoke_body


def test_openapi_json_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "AyDEO agent-007-theo API"


def test_openapi_diagnostic_invoke_ping_route_has_bearer_security() -> None:
    app.openapi_schema = None
    schema = app.openapi()
    path = schema["paths"]["/api/v1/bfa/diagnostics/invoke-ping"]["post"]
    assert path.get("security") == [{"HTTPBearer": []}]
    assert "BfaDiagnosticInvokePingResponse" in schema["components"]["schemas"]
