"""Unit tests for BFA API helpers and route edge cases."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Generator
from unittest.mock import AsyncMock, patch

import pytest
from bfa.aydeo_host import HostError, HostErrorCode, HostResponse
from fastapi.testclient import TestClient

from src.config import get_settings
from src.host.api import _serialize_execute_result
from src.host.facade import get_host_bfa
from src.host.factory import get_host_blueprint
from src.main import app
from src.shared.bfa_capability_contract import CAPABILITY_HEADER
from src.shared.test_utils import MockIdP, create_de_token
from tests.fixtures.case_policy_parity.canary_tools import CANARY_FIXTURE_VERSION, CANARY_QUERY_BOUNDED

pytestmark = pytest.mark.usefixtures("host_canaries")

DIAGNOSTIC_INVOKE_PING_PATH = "/api/v1/bfa/diagnostics/invoke-ping"


def test_serialize_execute_result_dict_steps() -> None:
    result = SimpleNamespace(
        status="succeeded",
        correlation_id="c1",
        trace=[{"step": 1}],
        assertions=[{"id": "a"}],
        outputs={"ok": True},
    )
    out = _serialize_execute_result(result)
    assert out.status == "succeeded"
    assert out.trace == [{"step": 1}]
    assert out.assertions == [{"id": "a"}]


def test_serialize_execute_result_model_dump() -> None:
    step = SimpleNamespace(model_dump=lambda mode="json": {"n": 1})
    assertion = SimpleNamespace(model_dump=lambda mode="json": {"id": "x"})
    result = SimpleNamespace(
        status="failed",
        correlation_id="c2",
        trace=[step],
        assertions=[assertion],
        outputs={},
    )
    out = _serialize_execute_result(result)
    assert out.trace == [{"n": 1}]
    assert out.assertions == [{"id": "x"}]


def test_serialize_execute_result_model_dump_outputs() -> None:
    outputs = SimpleNamespace(model_dump=lambda mode="json": {"plan_token": "tok"})
    result = SimpleNamespace(
        status="failed",
        correlation_id="c4",
        trace=[],
        assertions=[],
        outputs=outputs,
    )
    out = _serialize_execute_result(result)
    assert out.outputs == {"plan_token": "tok"}


def test_serialize_execute_result_skips_unknown_trace_entries() -> None:
    result = SimpleNamespace(
        status="succeeded",
        correlation_id="c3",
        trace=[object()],
        assertions=[object()],
        outputs="not-a-dict",
    )
    out = _serialize_execute_result(result)
    assert out.trace == []
    assert out.assertions == []
    assert out.outputs == {}


def test_invoke_unknown_tool_404() -> None:
    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    get_host_blueprint.cache_clear()
    de_id = get_settings().bfa_test_de_id
    de_token = create_de_token(de_id)
    cap = MockIdP.create_token(de_id, roles=["AyDEO-DE"])
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/bfa/invoke",
            headers={
                "Authorization": f"Bearer {de_token}",
                CAPABILITY_HEADER: cap,
            },
            json={
                "tool_name": "not.registered.tool",
                "tool_version": "1.0.0",
                "inputs": {},
            },
        )
    assert response.status_code == 404
    get_host_blueprint.cache_clear()
    get_host_bfa.cache_clear()
    get_settings.cache_clear()


def test_catalog_forbidden_without_bfa_role() -> None:
    get_settings.cache_clear()
    get_host_blueprint.cache_clear()
    token = MockIdP.create_token("user", roles=["AyDEO-User"])
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/bfa/catalog",
            headers={"Authorization": f"Bearer {token}"},
        )
    # HTTP auth is thin; Blueprint enforces roles and will reject invalid tokens.
    assert response.status_code in (401, 403)
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_catalog_management_unauthenticated_skips_runtime_fallback() -> None:
    get_settings.cache_clear()
    get_host_blueprint.cache_clear()
    token = MockIdP.create_token("mgr", roles=["AyDEO-Config-Admin"])
    mgmt_fail = HostResponse(
        status_code=401,
        error=HostError(
            code=HostErrorCode.UNAUTHENTICATED,
            message="token validation failed",
            status_code=401,
            details={"field": "management_token"},
        ),
    )
    runtime_mock = AsyncMock()
    with patch("src.host.api.get_host_blueprint") as mock_bp:
        blueprint = mock_bp.return_value
        blueprint.management_catalog = AsyncMock(return_value=mgmt_fail)
        blueprint.runtime_catalog = runtime_mock
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/bfa/catalog",
                headers={"Authorization": f"Bearer {token}"},
            )
    assert response.status_code == 401
    runtime_mock.assert_not_called()
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_invoke_forbidden_without_de_role() -> None:
    get_settings.cache_clear()
    get_host_blueprint.cache_clear()
    token = MockIdP.create_token("mgr", roles=["AyDEO-Config-Admin"])
    with TestClient(app) as client:
        response = client.post(
            DIAGNOSTIC_INVOKE_PING_PATH,
            headers={"Authorization": f"Bearer {token}"},
        )
    # HTTP auth is thin; Blueprint enforces DE role.
    assert response.status_code in (401, 403)
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_readiness_forbidden_for_de_token() -> None:
    get_settings.cache_clear()
    get_host_blueprint.cache_clear()
    token = create_de_token(get_settings().bfa_test_de_id)
    with TestClient(app) as client:
        response = client.get(
            "/health/ready",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_invoke_blueprint_error_response() -> None:
    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    get_host_blueprint.cache_clear()
    de_id = get_settings().bfa_test_de_id
    de_token = create_de_token(de_id)
    cap = MockIdP.create_token(
        de_id,
        roles=["AyDEO-DE"],
    )
    fail_resp = HostResponse(
        status_code=403,
        error=HostError(
            code=HostErrorCode.POLICY_DENIED,
            message="not allowed",
            status_code=403,
        ),
    )
    with patch("src.host.api.get_host_blueprint") as mock_bp, patch(
        "src.host.api.logger.warning"
    ) as mock_warning:
        blueprint = mock_bp.return_value
        blueprint.invoke = AsyncMock(return_value=fail_resp)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/bfa/invoke",
                headers={
                    "Authorization": f"Bearer {de_token}",
                    CAPABILITY_HEADER: cap,
                },
                json={
                    "tool_name": CANARY_QUERY_BOUNDED,
                    "tool_version": CANARY_FIXTURE_VERSION,
                    "inputs": {},
                },
            )
    assert response.status_code == 403
    mock_warning.assert_called_once()
    assert "bfa invoke denied" in mock_warning.call_args.args[0]
    get_host_blueprint.cache_clear()
    get_host_bfa.cache_clear()
    get_settings.cache_clear()


def test_diagnostic_invoke_ping_mode_off_returns_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_TEST_MODE", "false")
    get_settings.cache_clear()
    get_host_blueprint.cache_clear()
    response = client.post(DIAGNOSTIC_INVOKE_PING_PATH)
    assert response.status_code == 404
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_invoke_unreachable_assertion_guard() -> None:
    from bfa.aydeo_host import HostResponse

    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    get_host_blueprint.cache_clear()
    de_id = get_settings().bfa_test_de_id
    de_token = create_de_token(de_id)
    cap = MockIdP.create_token(de_id, roles=["AyDEO-DE"])
    fail_resp = HostResponse(status_code=500, body=None)
    with patch("src.host.api.get_host_blueprint") as mock_bp, patch(
        "src.host.api.raise_for_host_response",
        return_value=None,
    ):
        blueprint = mock_bp.return_value
        blueprint.invoke = AsyncMock(return_value=fail_resp)
        with TestClient(app) as client:
            with pytest.raises(AssertionError, match="unreachable"):
                client.post(
                    "/api/v1/bfa/invoke",
                    headers={
                        "Authorization": f"Bearer {de_token}",
                        CAPABILITY_HEADER: cap,
                    },
                    json={
                        "tool_name": CANARY_QUERY_BOUNDED,
                        "tool_version": CANARY_FIXTURE_VERSION,
                        "inputs": {},
                    },
                )
    get_host_blueprint.cache_clear()
    get_host_bfa.cache_clear()
    get_settings.cache_clear()


def test_invoke_passes_body_correlation_id_into_request_scope() -> None:
    from src.host.request_scope import set_runtime_request_context as real_set

    captured: dict[str, Any] = {}

    @contextmanager
    def _spy(**kwargs: Any) -> Generator[None, None, None]:
        captured["kwargs"] = kwargs
        with real_set(**kwargs):
            yield

    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    get_host_blueprint.cache_clear()
    de_id = get_settings().bfa_test_de_id
    de_token = create_de_token(de_id)
    cap = MockIdP.create_token(de_id, roles=["AyDEO-DE"])
    fail_resp = HostResponse(
        status_code=403,
        error=HostError(
            code=HostErrorCode.POLICY_DENIED,
            message="not allowed",
            status_code=403,
        ),
    )
    with (
        patch("src.host.api.get_host_blueprint") as mock_bp,
        patch("src.host.api.set_runtime_request_context", _spy),
    ):
        blueprint = mock_bp.return_value
        blueprint.invoke = AsyncMock(return_value=fail_resp)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/bfa/invoke",
                headers={
                    "Authorization": f"Bearer {de_token}",
                    CAPABILITY_HEADER: cap,
                },
                json={
                    "tool_name": CANARY_QUERY_BOUNDED,
                    "tool_version": CANARY_FIXTURE_VERSION,
                    "inputs": {},
                    "correlation_id": "cid-invoke-http",
                },
            )
    assert response.status_code == 403
    assert captured["kwargs"]["correlation_id"] == "cid-invoke-http"
    get_host_blueprint.cache_clear()
    get_host_bfa.cache_clear()
    get_settings.cache_clear()


def test_catalog_does_not_require_correlation_id() -> None:
    from src.host.request_scope import set_runtime_request_context as real_set

    captured: dict[str, Any] = {}

    @contextmanager
    def _spy(**kwargs: Any) -> Generator[None, None, None]:
        captured["kwargs"] = kwargs
        with real_set(**kwargs):
            yield

    get_settings.cache_clear()
    get_host_blueprint.cache_clear()
    token = MockIdP.create_token("mgr", roles=["AyDEO-Config-Admin"])
    mgmt_fail = HostResponse(
        status_code=401,
        error=HostError(
            code=HostErrorCode.UNAUTHENTICATED,
            message="token validation failed",
            status_code=401,
            details={"field": "management_token"},
        ),
    )
    with (
        patch("src.host.api.get_host_blueprint") as mock_bp,
        patch("src.host.api.set_runtime_request_context", _spy),
    ):
        blueprint = mock_bp.return_value
        blueprint.management_catalog = AsyncMock(return_value=mgmt_fail)
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/bfa/catalog",
                headers={"Authorization": f"Bearer {token}"},
            )
    assert response.status_code == 401
    assert "correlation_id" not in captured["kwargs"]
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()
