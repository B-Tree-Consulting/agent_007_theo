"""Structured API error bodies."""

from __future__ import annotations

from typing import Any


def error_response_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}
