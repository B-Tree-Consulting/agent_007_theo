"""Unit tests for shared auth helpers."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from src.config import get_settings
from src.shared import auth as auth_module
from src.shared.auth import (
    ENTRA_ROLE_CLAIM,
    AuthContext,
    _resolve_roles,
    get_current_user,
)
from src.shared.errors import error_response_body
from src.shared.test_utils import MockIdP


def test_error_response_body() -> None:
    body = error_response_body("code", "msg", {"k": 1})
    assert body["error"]["code"] == "code"
    assert body["error"]["details"] == {"k": 1}


def test_resolve_roles_from_header() -> None:
    assert _resolve_roles("AyDEO-DE, DRIS-Admin", {}) == ["AyDEO-DE", "DRIS-Admin"]


def test_resolve_roles_header_whitespace_only_falls_through() -> None:
    assert _resolve_roles(" , ", {"roles": ["AyDEO-DE"]}) == ["AyDEO-DE"]


def test_resolve_roles_from_payload_list() -> None:
    assert _resolve_roles(None, {"roles": ["AyDEO-DE"]}) == ["AyDEO-DE"]


def test_resolve_roles_from_payload_string() -> None:
    assert _resolve_roles(None, {"roles": "AyDEO-DE"}) == ["AyDEO-DE"]


def test_resolve_roles_from_entra_claim() -> None:
    assert _resolve_roles(None, {ENTRA_ROLE_CLAIM: ["AyDEO-Config-Admin"]}) == [
        "AyDEO-Config-Admin"
    ]


def test_resolve_roles_entra_string() -> None:
    assert _resolve_roles(None, {ENTRA_ROLE_CLAIM: "AyDEO-DE"}) == ["AyDEO-DE"]


def test_resolve_roles_empty() -> None:
    assert _resolve_roles(None, {}) == []


def test_auth_context_list_scopes() -> None:
    ctx = AuthContext({"sub": "u", "roles": [], "scope": ["a", "b"]})
    assert ctx.scopes == ["a", "b"]


def test_get_current_user_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})

    async def _run() -> AuthContext:
        return await get_current_user(request, None)

    ctx = asyncio.run(_run())
    assert ctx.roles == ["AyDEO-Config-Admin"]


def test_get_current_user_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})

    async def _run() -> None:
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request, None)
        assert exc.value.status_code == 401

    asyncio.run(_run())


def test_get_current_user_production_thin_bearer_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "false")
    get_settings.cache_clear()
    token = MockIdP.create_token("sub", roles=["AyDEO-DE"])
    request = Request({"type": "http", "headers": []})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    async def _run() -> None:
        # Production mode validation occurs in Blueprint/kit adapters; shared auth is a thin bearer extractor.
        ctx = await get_current_user(request, creds)
        assert ctx.access_token == token
        assert ctx.roles == []

    asyncio.run(_run())


def test_get_current_user_whitespace_credentials_use_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    token = MockIdP.create_token("sub", roles=["AyDEO-Config-Admin"])
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="   ")

    async def _run() -> AuthContext:
        ctx = await get_current_user(request, creds)
        assert ctx.access_token == token

    asyncio.run(_run())


def test_get_current_user_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")

    async def _run() -> None:
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request, creds)
        assert exc.value.status_code == 401

    asyncio.run(_run())


def test_get_current_user_x_user_roles_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    token = MockIdP.create_token("sub", roles=[])
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-user-roles", b"AyDEO-Config-Admin")],
        }
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    async def _run() -> AuthContext:
        return await auth_module.get_current_user(request, creds)

    ctx = asyncio.run(_run())
    assert ctx.roles == ["AyDEO-Config-Admin"]


def test_normalize_capability_header_variants() -> None:
    from src.shared.bfa_capability_contract import normalize_capability_header_value

    assert normalize_capability_header_value(None) is None
    assert normalize_capability_header_value("  ") is None
    assert normalize_capability_header_value("Bearer tok") == "tok"
    assert normalize_capability_header_value("tok") == "tok"
