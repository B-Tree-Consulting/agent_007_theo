"""FastAPI transport for AydeoHostBlueprint HostResponse."""

from __future__ import annotations

from typing import Any

from bfa.aydeo_host import HostErrorCode, HostResponse
from fastapi import HTTPException, status

from src.shared.errors import error_response_body

_JSON_SAFE = (str, int, float, bool, type(None))


def validation_error_detail(errors: Any) -> list[dict[str, Any]] | None:
    """Turn a kit errors list into a Chat-readable 422 detail list.

    A non-list is ignored so callers do not stringify errors into the message.
    """
    if not isinstance(errors, list) or not errors:
        return None
    detail: list[dict[str, Any]] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        loc = item.get("loc") or ()
        if isinstance(loc, (list, tuple)):
            loc_out = [str(part) for part in loc]
        else:
            loc_out = [str(loc)]
        entry: dict[str, Any] = {
            "type": str(item.get("type") or "value_error"),
            "loc": loc_out,
            "msg": str(item.get("msg") or ""),
        }
        if "input" in item and isinstance(item.get("input"), _JSON_SAFE):
            entry["input"] = item.get("input")
        detail.append(entry)
    return detail


def raise_for_host_response(
    resp: HostResponse,
    *,
    tool_name: str | None = None,
) -> Any:
    if resp.ok:
        return resp.body

    err = resp.error
    if err is None:
        raise HTTPException(status_code=resp.status_code, detail="BFA host error")

    message = err.message
    details = err.details or {}

    if err.code == HostErrorCode.INVALID_CONTEXT:
        if tool_name and "unknown tool" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown tool: {tool_name}",
            )
        validation_detail = validation_error_detail(details.get("errors"))
        if validation_detail is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=validation_detail,
            )
        if err.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)

    if err.code == HostErrorCode.POLICY_DENIED:
        nested = details.get("error")
        if isinstance(nested, dict):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=nested)
        if "not allowed" in message.lower() or "capability" in message.lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
        if "version" in message.lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)

    if err.code == HostErrorCode.UNAUTHENTICATED:
        detail: str | dict[str, Any] = message
        if details:
            detail = {
                "error": {
                    "code": "unauthenticated",
                    "message": message,
                    "details": details,
                }
            }
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if err.code == HostErrorCode.FORBIDDEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)

    if err.code == HostErrorCode.HOST_UNAVAILABLE:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message)

    raise HTTPException(status_code=err.status_code, detail=message)
