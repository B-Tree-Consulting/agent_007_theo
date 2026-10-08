"""Canonical CMS case open/closed lifecycle (adapted from aydeo_be cms/lifecycle.py)."""

from __future__ import annotations

from enum import Enum
from typing import Any

TERMINAL_CASE_STATUSES = frozenset({"completed", "cancelled", "rejected"})
OPEN_CASE_STATUSES = frozenset({"created", "assigned", "in_progress", "resolved"})


def _normalize_status(status: Any) -> str | None:
    if status is None:
        return None
    if isinstance(status, Enum):
        return str(status.value)
    return str(status)


def is_case_open(case: Any) -> bool:
    """
    True when the case is actively open per product#560 (P1 canonical lifecycle).

    Accepts an ORM Case row or a minimal projection (e.g. CaseResponse) with
    deleted_at, completed_at, and status attributes.
    """
    deleted_at = getattr(case, "deleted_at", None)
    if deleted_at is not None:
        return False

    completed_at = getattr(case, "completed_at", None)
    if completed_at is not None:
        return False

    status = _normalize_status(getattr(case, "status", None))
    if status is None:
        return False
    if status in TERMINAL_CASE_STATUSES:
        return False
    if status in OPEN_CASE_STATUSES:
        return True
    return False
