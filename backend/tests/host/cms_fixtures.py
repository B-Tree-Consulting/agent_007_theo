"""CMS CaseResponse builders for host tests."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from aydeo_cms_client.internal_models import CaseInvokeFactsResponse
from aydeo_cms_client.models import CaseResponse

_DEFAULT_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_OPEN_CASE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def default_open_case_id() -> str:
    return DEFAULT_OPEN_CASE_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_case_response(
    *,
    case_id: str | UUID,
    case_state: str,
    resolution_hold: bool | None = None,
    status: str | None = None,
) -> CaseResponse:
    case_uuid = UUID(str(case_id))
    now = _now()
    if case_state == "closed":
        mapped_status = "completed"
        completed_at = now
        hold = False if resolution_hold is None else resolution_hold
    elif case_state == "held":
        mapped_status = "in_progress"
        completed_at = None
        hold = True if resolution_hold is None else resolution_hold
    elif case_state == "open":
        mapped_status = "in_progress"
        completed_at = None
        hold = False if resolution_hold is None else resolution_hold
    else:
        mapped_status = "in_progress"
        completed_at = None
        hold = False if resolution_hold is None else resolution_hold

    resolved_status = status if status is not None else mapped_status
    if resolved_status in {"completed", "cancelled", "rejected"} and completed_at is None:
        completed_at = now

    return CaseResponse(
        id=case_uuid,
        created_by_user_id=_DEFAULT_USER_ID,
        requested_by_user_id=_DEFAULT_USER_ID,
        assigned_to_user_id=_DEFAULT_USER_ID,
        intent_description="test case",
        status=resolved_status,
        priority="normal",
        created_at=now,
        updated_at=now,
        completed_at=completed_at,
        resolution_hold=hold,
    )


def build_invoke_facts_response(
    *,
    exists: bool = True,
    is_open: bool | None = True,
    is_held: bool | None = False,
    status: str | None = "in_progress",
    assignment_version: int | None = None,
    completion_contract_version: int | None = None,
    assignee_user_id: str | None = None,
    assignee_subject: str | None = None,
    consulting_entitled: bool = False,
) -> CaseInvokeFactsResponse:
    return CaseInvokeFactsResponse(
        exists=exists,
        is_open=is_open,
        is_held=is_held,
        status=status,
        assignment_version=assignment_version,
        completion_contract_version=completion_contract_version,
        assignee_user_id=assignee_user_id,
        assignee_subject=assignee_subject,
        consulting_entitled=consulting_entitled,
    )


def build_invoke_facts_for_case_state(
    case_state: str,
    *,
    status: str | None = None,
    **overrides: object,
) -> CaseInvokeFactsResponse:
    if case_state == "closed":
        mapped = dict(exists=True, is_open=False, is_held=False, status="completed")
    elif case_state == "held":
        mapped = dict(exists=True, is_open=True, is_held=True, status="in_progress")
    elif case_state == "unknown":
        mapped = dict(exists=False, is_open=None, is_held=None, status=None)
    else:
        mapped = dict(exists=True, is_open=True, is_held=False, status="in_progress")
    if status is not None:
        mapped["status"] = status
    mapped.update(overrides)
    return build_invoke_facts_response(**mapped)  # type: ignore[arg-type]
