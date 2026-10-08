"""Unit tests for host auth route dependencies."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from src.config import get_settings
from src.host.auth import _validated_de_id_from_auth_context, require_runtime_bearer
from src.shared.auth import AuthContext
from src.shared.test_utils import MockIdP


def test_bfa_catalog_access_is_management() -> None:
    from src.host.auth import BFA_CATALOG_MODE_MANAGEMENT, BfaCatalogAccess
    from src.shared.auth import AuthContext

    access = BfaCatalogAccess(
        token="t",
        mode=BFA_CATALOG_MODE_MANAGEMENT,
        auth_ctx=AuthContext({"sub": "u"}),
    )
    assert access.is_management is True


def test_validated_de_id_missing_subject() -> None:
    with pytest.raises(HTTPException) as exc:
        _validated_de_id_from_auth_context(AuthContext({"roles": ["AyDEO-DE"]}))
    assert exc.value.status_code == 403


def test_require_runtime_bearer_missing_de_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    token = MockIdP.create_token("mgr", roles=["AyDEO-Config-Admin"])
    request = Request({"type": "http", "headers": []})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    async def _run() -> None:
        # HTTP layer is thin; Blueprint/kit validators enforce DE role.
        access = await require_runtime_bearer(request, creds)
        assert access.token == token

    asyncio.run(_run())


def test_require_bearer_token_missing_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.host.auth import _require_bearer_token

    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})

    async def _run() -> None:
        with pytest.raises(HTTPException) as exc:
            await _require_bearer_token(request, None)
        assert exc.value.status_code == 401

    asyncio.run(_run())


def test_require_readiness_access_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.host.auth import require_readiness_access

    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})

    async def _run() -> None:
        await require_readiness_access(request, None)

    asyncio.run(_run())


def test_require_catalog_bearer_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.host.auth import require_catalog_bearer

    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})

    async def _run() -> None:
        access = await require_catalog_bearer(request, None)
        assert access.mode == "runtime"
        assert access.de_id == get_settings().bfa_test_de_id

    asyncio.run(_run())


def test_require_runtime_bearer_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.host.auth import require_runtime_bearer

    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})

    async def _run() -> None:
        access = await require_runtime_bearer(request, None)
        assert access.de_id == get_settings().bfa_test_de_id

    asyncio.run(_run())


def test_require_bearer_token_raises_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock, patch

    from src.host.auth import _require_bearer_token

    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    request = Request({"type": "http", "headers": []})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")

    async def _run() -> None:
        with patch(
            "src.host.auth.get_current_user",
            new=AsyncMock(return_value=AuthContext({"sub": "de"}, access_token=None)),
        ):
            with pytest.raises(HTTPException) as exc:
                await _require_bearer_token(request, creds)
            assert exc.value.status_code == 401

    asyncio.run(_run())
