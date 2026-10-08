"""Unit tests for host HTTP error mapping."""

from __future__ import annotations

import pytest
from bfa.aydeo_host import HostError, HostErrorCode, HostResponse
from fastapi import HTTPException

from src.host.http import raise_for_host_response


def _err(
    code: HostErrorCode,
    message: str,
    *,
    status_code: int = 400,
    details: dict | None = None,
) -> HostResponse:
    return HostResponse(
        status_code=status_code,
        error=HostError(code=code, message=message, status_code=status_code, details=details or {}),
    )


def test_raise_returns_body_on_success() -> None:
    body = raise_for_host_response(HostResponse(status_code=200, body={"status": "ok"}))
    assert body == {"status": "ok"}


def test_raise_generic_error_without_err_object() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(HostResponse(status_code=500, error=None))
    assert exc.value.status_code == 500
    assert exc.value.detail == "BFA host error"


def test_raise_unknown_tool_404() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(
            _err(HostErrorCode.INVALID_CONTEXT, "unknown tool: x", status_code=404),
            tool_name="x",
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Unknown tool: x"


def test_raise_invalid_input_schema_422() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(
            _err(
                HostErrorCode.INVALID_CONTEXT,
                "input schema mismatch",
                details={"tool": "t", "errors": ["bad"]},
            ),
            tool_name="t",
        )
    assert exc.value.status_code == 422
    assert "Invalid inputs for t" in str(exc.value.detail)


def test_raise_invalid_context_404_status() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(
            _err(HostErrorCode.INVALID_CONTEXT, "missing", status_code=404),
        )
    assert exc.value.status_code == 404


def test_raise_policy_denied_capability() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(_err(HostErrorCode.POLICY_DENIED, "capability denied"))
    assert exc.value.status_code == 403


def test_raise_policy_denied_version() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(_err(HostErrorCode.POLICY_DENIED, "wrong tool version"))
    assert exc.value.status_code == 403


def test_raise_policy_denied_generic() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(_err(HostErrorCode.POLICY_DENIED, "nope"))
    assert exc.value.status_code == 403


def test_raise_policy_denied_nested_journey_error() -> None:
    nested = {
        "error": {
            "code": "journey_disallows_tool",
            "message": "Case-effect tools are not permitted in the current journey state",
            "details": {},
        }
    }
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(
            _err(
                HostErrorCode.POLICY_DENIED,
                "Case-effect tools are not permitted in the current journey state",
                status_code=403,
                details={"error": nested},
            )
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == nested


def test_raise_unauthenticated() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(_err(HostErrorCode.UNAUTHENTICATED, "bad token", status_code=401))
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


def test_raise_unauthenticated_structured_detail() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(
            _err(
                HostErrorCode.UNAUTHENTICATED,
                "token validation failed",
                status_code=401,
                details={"field": "management_token", "reason": "DecodeError"},
            )
        )
    assert exc.value.status_code == 401
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["error"]["code"] == "unauthenticated"
    assert detail["error"]["details"]["field"] == "management_token"


def test_raise_forbidden() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(_err(HostErrorCode.FORBIDDEN, "forbidden", status_code=403))
    assert exc.value.status_code == 403


def test_raise_host_unavailable() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(_err(HostErrorCode.HOST_UNAVAILABLE, "down", status_code=503))
    assert exc.value.status_code == 503


def test_raise_fallback_status() -> None:
    with pytest.raises(HTTPException) as exc:
        raise_for_host_response(
            HostResponse(
                status_code=418,
                error=HostError(
                    code=HostErrorCode.INVALID_CONTEXT,
                    message="teapot",
                    status_code=418,
                ),
            )
        )
    assert exc.value.status_code == 418
