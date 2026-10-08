"""Direct tests for main app helpers."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from src import main as main_module
from src.config import get_settings
from src.host.factory import get_host_blueprint
from src.shared.test_utils import create_config_admin_token


def test_readiness_check_authorization_header_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    get_host_blueprint.cache_clear()
    token = create_config_admin_token()

    async def _run() -> dict:
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", f"Bearer {token}".encode())],
            }
        )
        return await main_module.readiness_check(
            request,
            None,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=""),
        )

    body = asyncio.run(_run())
    assert body["service"] == get_settings().bfa_service_slug
    assert body["status"] in ("ready", "healthy", "ok")
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_readiness_check_non_bearer_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    get_host_blueprint.cache_clear()

    async def _run() -> None:
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Basic not-bearer")],
            }
        )
        with pytest.raises(HTTPException) as exc:
            await main_module.readiness_check(request, None, None)
        assert exc.value.status_code == 401

    asyncio.run(_run())
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_custom_openapi_skips_non_dict_path_methods() -> None:
    from unittest.mock import patch

    main_module.app.openapi_schema = None
    fake_schema = {
        "paths": {
            "/health": {"get": {"responses": {}}, "parameters": []},
            "/health/ready": {"get": {"responses": {}}, "x-foo": "bar"},
            "/api/v1/bfa/invoke": {"post": {"responses": {}}, "deprecated": True},
            "/api/v1/bfa/catalog": {"get": {"responses": {}}, "summary": "x"},
            "/other": {"get": {"responses": {}}},
        }
    }
    with patch("src.main.get_openapi", return_value=fake_schema):
        schema = main_module.custom_openapi()
    assert schema["paths"]["/health"]["get"]["security"] == []
    assert schema["paths"]["/health/ready"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in schema["paths"]["/other"]["get"]
    main_module.app.openapi_schema = None


def test_http_exception_handler_structured_error_detail() -> None:
    from fastapi import HTTPException

    exc = HTTPException(
        status_code=401,
        detail={
            "error": {
                "code": "unauthenticated",
                "message": "token validation failed",
                "details": {"field": "management_token"},
            }
        },
    )
    response = asyncio.run(main_module.http_exception_handler(Request({"type": "http"}), exc))
    assert response.status_code == 401
    assert b"unauthenticated" in response.body


def test_custom_openapi_cached() -> None:
    main_module.app.openapi_schema = None
    first = main_module.custom_openapi()
    second = main_module.custom_openapi()
    assert first is second
    assert "/health" in first["paths"]


def test_http_exception_handler_plain_detail() -> None:
    from fastapi import HTTPException

    exc = HTTPException(status_code=400, detail="bad request")
    response = asyncio.run(main_module.http_exception_handler(Request({"type": "http"}), exc))
    assert response.status_code == 400
    assert response.body is not None
