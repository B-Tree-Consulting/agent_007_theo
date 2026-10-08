"""Unit tests for AydeoCaseStateAdapter invoke-facts consume."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from aydeo_cms_client.errors import (
    CmsForbiddenError,
    CmsServiceUnavailableError,
    CmsTimeoutError,
    CmsUnauthorizedError,
)

from src.config import Settings, get_settings
from src.host.case_state_adapter import (
    AydeoCaseStateAdapter,
    _dependency_failure_from_client_error,
    _detail_code,
)
from tests.host.cms_fixtures import build_invoke_facts_response

_PATCH = "src.host.case_state_adapter.AydeoCmsInternalClient.get_case_invoke_facts"


@pytest.fixture(autouse=True)
def _cms_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AYDEO_CMS_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN", "test-internal-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_resolve_assignee_does_not_copy_invoking_subject() -> None:
    captured: dict[str, object] = {}

    async def _facts(case_id, *, invoking_subject=None, thread_id=None):
        captured["case_id"] = case_id
        captured["invoking_subject"] = invoking_subject
        captured["thread_id"] = thread_id
        return build_invoke_facts_response(
            assignee_subject="cms-assignee",
            assignee_user_id="usr-1",
            consulting_entitled=False,
            status="in_progress",
            assignment_version=3,
            completion_contract_version=2,
        )

    adapter = AydeoCaseStateAdapter()
    case_id = "not-a-uuid"
    with patch(_PATCH, new=AsyncMock(side_effect=_facts)):
        facts = await adapter.resolve(
            case_id=case_id,
            invoking_subject="caller-de",
            thread_id="thread-1",
        )
    assert captured == {
        "case_id": case_id,
        "invoking_subject": "caller-de",
        "thread_id": "thread-1",
    }
    assert facts.exists is True
    assert facts.is_open is True
    assert facts.is_held is False
    assert facts.status == "in_progress"
    assert facts.assignee_subject == "cms-assignee"
    assert facts.assignee_user_id == "usr-1"
    assert facts.consulting_entitled is False
    assert facts.assignment_version == 3
    assert facts.completion_contract_version == 2
    assert facts.assignment_acceptance_status is None


@pytest.mark.anyio
async def test_resolve_entitled_consultant() -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(
        _PATCH,
        new=AsyncMock(
            return_value=build_invoke_facts_response(
                assignee_subject="other-assignee",
                consulting_entitled=True,
            )
        ),
    ):
        facts = await adapter.resolve(case_id=str(uuid4()), invoking_subject="consultant-de")
    assert facts.consulting_entitled is True
    assert facts.assignee_subject == "other-assignee"
    assert facts.assignee_subject != "consultant-de"


@pytest.mark.anyio
async def test_resolve_wrong_subject_keeps_authoritative_assignee() -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(
        _PATCH,
        new=AsyncMock(
            return_value=build_invoke_facts_response(
                assignee_subject="real-assignee",
                consulting_entitled=False,
            )
        ),
    ):
        facts = await adapter.resolve(case_id=str(uuid4()), invoking_subject="wrong-de")
    assert facts.assignee_subject == "real-assignee"
    assert facts.consulting_entitled is False


@pytest.mark.anyio
async def test_resolve_not_found_is_exists_false() -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(
        _PATCH,
        new=AsyncMock(
            return_value=build_invoke_facts_response(
                exists=False,
                is_open=None,
                is_held=None,
                status=None,
            )
        ),
    ):
        facts = await adapter.resolve(case_id="not-a-uuid")
    assert facts.exists is False
    assert facts.dependency_failure is None


@pytest.mark.anyio
async def test_resolve_soft_delete_exists_true_not_open() -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(
        _PATCH,
        new=AsyncMock(
            return_value=build_invoke_facts_response(
                exists=True,
                is_open=False,
                is_held=False,
                status="completed",
            )
        ),
    ):
        facts = await adapter.resolve(case_id=str(uuid4()))
    assert facts.exists is True
    assert facts.is_open is False


@pytest.mark.anyio
async def test_resolve_held_case_pass_through() -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(
        _PATCH,
        new=AsyncMock(
            return_value=build_invoke_facts_response(
                is_open=True,
                is_held=True,
                status="in_progress",
            )
        ),
    ):
        facts = await adapter.resolve(case_id=str(uuid4()))
    assert facts.is_open is True
    assert facts.is_held is True


@pytest.mark.parametrize(
    "exc",
    [
        CmsUnauthorizedError("unauthorized", status_code=401),
        CmsForbiddenError("forbidden", status_code=403),
        CmsServiceUnavailableError(
            "unavailable",
            status_code=503,
            detail='{"code": "scope_unavailable"}',
        ),
        CmsTimeoutError("timed out"),
        RuntimeError("network"),
    ],
)
@pytest.mark.anyio
async def test_resolve_client_errors_are_scope_unavailable(exc: BaseException) -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(_PATCH, new=AsyncMock(side_effect=exc)):
        facts = await adapter.resolve(case_id=str(uuid4()))
    assert facts.dependency_failure == "scope_unavailable"


@pytest.mark.anyio
async def test_resolve_hold_unavailable_from_mocked_detail() -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(
        _PATCH,
        new=AsyncMock(
            side_effect=CmsServiceUnavailableError(
                "unavailable",
                status_code=503,
                detail='{"code": "hold_unavailable"}',
            )
        ),
    ):
        facts = await adapter.resolve(case_id=str(uuid4()))
    assert facts.dependency_failure == "hold_unavailable"


def test_detail_code_shapes() -> None:
    assert _detail_code(None) is None
    assert _detail_code(123) is None
    assert _detail_code("  ") is None
    assert _detail_code("other") is None
    assert _detail_code("hold_unavailable") == "hold_unavailable"
    assert _detail_code('{"code": "hold_unavailable"}') == "hold_unavailable"
    assert _detail_code({"code": "hold_unavailable"}) == "hold_unavailable"
    assert _detail_code({"detail": {"code": "hold_unavailable"}}) == "hold_unavailable"
    assert _detail_code({"detail": "not-a-dict"}) is None
    assert _detail_code('["not-an-object"]') is None
    err = CmsServiceUnavailableError("unavailable", status_code=503, detail="hold_unavailable")
    assert _dependency_failure_from_client_error(err) == "hold_unavailable"


@pytest.mark.anyio
async def test_resolve_missing_cms_base_url_scope_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    isolated = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
        aydeo_cms_base_url=None,
        aydeo_platform_internal_service_token="test-internal-token",
    )
    monkeypatch.setattr("src.host.case_state_adapter.get_settings", lambda: isolated)
    adapter = AydeoCaseStateAdapter()
    facts = await adapter.resolve(case_id=str(uuid4()))
    assert facts.dependency_failure == "scope_unavailable"


@pytest.mark.anyio
async def test_resolve_missing_token_scope_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    isolated = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
        aydeo_cms_base_url="http://localhost:8000",
        aydeo_platform_internal_service_token=None,
    )
    monkeypatch.setattr("src.host.case_state_adapter.get_settings", lambda: isolated)
    adapter = AydeoCaseStateAdapter()
    facts = await adapter.resolve(case_id=str(uuid4()))
    assert facts.dependency_failure == "scope_unavailable"


@pytest.mark.anyio
async def test_resolve_blank_token_scope_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    isolated = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
        aydeo_cms_base_url="http://localhost:8000",
        aydeo_platform_internal_service_token="   ",
    )
    monkeypatch.setattr("src.host.case_state_adapter.get_settings", lambda: isolated)
    adapter = AydeoCaseStateAdapter()
    facts = await adapter.resolve(case_id=str(uuid4()))
    assert facts.dependency_failure == "scope_unavailable"


@pytest.mark.anyio
async def test_resolve_strips_blank_kwargs_to_none() -> None:
    captured: dict[str, object] = {}

    async def _facts(case_id, *, invoking_subject=None, thread_id=None):
        captured["invoking_subject"] = invoking_subject
        captured["thread_id"] = thread_id
        return build_invoke_facts_response(status="assigned")

    adapter = AydeoCaseStateAdapter()
    with patch(_PATCH, new=AsyncMock(side_effect=_facts)):
        facts = await adapter.resolve(
            case_id=str(uuid4()),
            invoking_subject="   ",
            thread_id="  ",
        )
    assert captured["invoking_subject"] is None
    assert captured["thread_id"] is None
    assert facts.status == "assigned"
    assert facts.completion_contract_version is None


@pytest.mark.anyio
async def test_resolve_does_not_default_completion_contract_version() -> None:
    adapter = AydeoCaseStateAdapter()
    with patch(
        _PATCH,
        new=AsyncMock(
            return_value=build_invoke_facts_response(
                status="assigned",
                completion_contract_version=None,
            )
        ),
    ):
        facts = await adapter.resolve(case_id=str(uuid4()), invoking_subject="de-subject")
    assert facts.completion_contract_version is None
    assert facts.assignment_acceptance_status is None
