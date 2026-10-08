"""Unit tests for case lifecycle helper."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aydeo_cms_client.models import CaseResponse

from src.host.case_lifecycle import _normalize_status, is_case_open


class _StatusEnum(Enum):
    in_progress = "in_progress"
    completed = "completed"


def _case(**overrides) -> CaseResponse:
    now = datetime.now(timezone.utc)
    base = {
        "id": uuid4(),
        "created_by_user_id": uuid4(),
        "requested_by_user_id": uuid4(),
        "assigned_to_user_id": uuid4(),
        "intent_description": "test",
        "status": "in_progress",
        "priority": "normal",
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return CaseResponse(**base)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, None),
        ("in_progress", "in_progress"),
        (_StatusEnum.in_progress, "in_progress"),
        (_StatusEnum.completed, "completed"),
    ],
)
def test_normalize_status(status: object, expected: str | None) -> None:
    assert _normalize_status(status) == expected


@pytest.mark.parametrize(
    "status",
    ["created", "assigned", "in_progress", "resolved"],
)
def test_is_case_open_active_statuses(status: str) -> None:
    assert is_case_open(_case(status=status)) is True


@pytest.mark.parametrize(
    "status",
    ["completed", "cancelled", "rejected"],
)
def test_is_case_open_terminal_status_without_completed_at(status: str) -> None:
    assert is_case_open(_case(status=status, completed_at=None)) is False


def test_is_case_open_terminal_with_completed_at() -> None:
    assert is_case_open(_case(status="completed", completed_at=datetime.now(timezone.utc))) is False


def test_is_case_open_deleted() -> None:
    assert is_case_open(_case(deleted_at=datetime.now(timezone.utc))) is False


def test_is_case_open_completed_at_closes_even_if_status_open() -> None:
    assert is_case_open(_case(status="in_progress", completed_at=datetime.now(timezone.utc))) is False


def test_is_case_open_missing_status() -> None:
    case = SimpleNamespace(deleted_at=None, completed_at=None, status=None)
    assert is_case_open(case) is False


def test_is_case_open_unknown_status() -> None:
    assert is_case_open(_case(status="weird_custom_status")) is False


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_is_case_open_dropped_legacy_statuses_fail_closed(status: str) -> None:
    assert is_case_open(_case(status=status)) is False


def test_is_case_open_enum_status() -> None:
    case = SimpleNamespace(
        deleted_at=None,
        completed_at=None,
        status=_StatusEnum.in_progress,
    )
    assert is_case_open(case) is True
