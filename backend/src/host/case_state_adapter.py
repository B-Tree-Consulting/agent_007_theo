"""HTTP CaseStateAdapter for AyDEO host sample (host-trusted invoke-facts)."""

from __future__ import annotations

import json

from aydeo_cms_client import AydeoCmsInternalClient
from bfa.aydeo_host.case_state import CaseStateAdapter, CaseStateFacts

from src.config import get_settings


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _detail_code(detail: object) -> str | None:
    if detail is None:
        return None
    if isinstance(detail, dict):
        nested = detail.get("detail")
        if isinstance(nested, dict) and nested.get("code") is not None:
            return str(nested["code"])
        code = detail.get("code")
        return str(code) if code is not None else None
    if not isinstance(detail, str):
        return None
    stripped = detail.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped if stripped == "hold_unavailable" else None
    if isinstance(parsed, dict):
        return _detail_code(parsed)
    return None


def _dependency_failure_from_client_error(exc: BaseException) -> str:
    if _detail_code(getattr(exc, "detail", None)) == "hold_unavailable":
        return "hold_unavailable"
    return "scope_unavailable"


def _scope_unavailable() -> CaseStateFacts:
    return CaseStateFacts(
        exists=None,
        is_open=None,
        is_held=None,
        dependency_failure="scope_unavailable",
    )


class AydeoCaseStateAdapter:
    """Resolve complete case facts from host-trusted CMS invoke-facts."""

    async def resolve(
        self,
        *,
        case_id: str,
        thread_id: str | None = None,
        invoking_subject: str | None = None,
    ) -> CaseStateFacts:
        settings = get_settings()
        base_url = (settings.aydeo_cms_base_url or "").strip()
        token = (settings.aydeo_platform_internal_service_token or "").strip()
        if not base_url or not token:
            return _scope_unavailable()

        subject = _blank_to_none(invoking_subject)
        thread = _blank_to_none(thread_id)
        client = AydeoCmsInternalClient(base_url=base_url, internal_service_token=token)
        try:
            dto = await client.get_case_invoke_facts(
                case_id,
                invoking_subject=subject,
                thread_id=thread,
            )
        except Exception as exc:
            failure = _dependency_failure_from_client_error(exc)
            return CaseStateFacts(
                exists=None,
                is_open=None,
                is_held=None,
                dependency_failure=failure,  # type: ignore[arg-type]
            )

        return CaseStateFacts(
            exists=dto.exists,
            is_open=dto.is_open,
            is_held=dto.is_held,
            status=dto.status,
            assignment_version=dto.assignment_version,
            completion_contract_version=dto.completion_contract_version,
            assignee_user_id=dto.assignee_user_id,
            assignee_subject=dto.assignee_subject,
            consulting_entitled=dto.consulting_entitled,
        )


__all__ = ["AydeoCaseStateAdapter", "CaseStateAdapter"]
