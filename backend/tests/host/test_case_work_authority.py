"""P1 journey authority consume — Assigned reads vs effects, terminal capture."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from bfa.aydeo_host import CaseStateFacts
from fastapi.testclient import TestClient

from src.shared.test_utils import create_de_token
from tests.fixtures.case_policy_parity.canary_tools import (
    CANARY_ACTION_MEDIUM,
    CANARY_FIXTURE_VERSION,
    CANARY_QUERY_BOUNDED,
)
from tests.host.cms_fixtures import (
    build_invoke_facts_for_case_state,
    build_invoke_facts_response,
    default_open_case_id,
)
from tests.host.http_helpers import assert_deferred, runtime_headers

_OTHER_ASSIGNEE = "other-assignee-de"
_INVOKE_FACTS_PATCH = "src.host.case_state_adapter.AydeoCmsInternalClient.get_case_invoke_facts"

pytestmark = pytest.mark.usefixtures("host_canaries")


def _deny_body(response: Any) -> dict[str, Any]:
    payload = response.json()
    if isinstance(payload, dict) and isinstance(payload.get("detail"), dict):
        return payload["detail"]
    return payload if isinstance(payload, dict) else {}


def _recovery_action(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    details = err.get("details") if isinstance(err.get("details"), dict) else {}
    recovery = details.get("recovery") if isinstance(details.get("recovery"), dict) else {}
    if not recovery and isinstance(details.get("details"), dict):
        nested = details["details"]
        if isinstance(nested.get("recovery"), dict):
            recovery = nested["recovery"]
    return recovery.get("action")


def _error_code(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    return err.get("code")


def _invoke(
    client: TestClient,
    *,
    de_id: str,
    capability_token: str,
    tool_name: str,
    tool_version: str,
    inputs: dict[str, Any] | None = None,
    thread_id: str | None = None,
    turn_invoke_grant: str | None = None,
) -> Any:
    de_token = create_de_token(de_id)
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_version": tool_version,
        "inputs": inputs or {},
        "case_id": default_open_case_id(),
        "correlation_id": f"cid-{tool_name}",
    }
    if thread_id is not None:
        payload["thread_id"] = thread_id
    if turn_invoke_grant is not None:
        payload["turn_invoke_grant"] = turn_invoke_grant
    return client.post(
        "/api/v1/bfa/invoke",
        headers=runtime_headers(de_token, capability_token),
        json=payload,
    )


@pytest.fixture
def _assigned_cms() -> None:
    async def _get_facts(case_id, *, invoking_subject=None, thread_id=None):
        del case_id, invoking_subject, thread_id
        return build_invoke_facts_for_case_state("open", status="assigned")

    with patch(
        _INVOKE_FACTS_PATCH,
        new=AsyncMock(side_effect=_get_facts),
    ):
        yield


def test_assigned_get_menu_succeeds(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    _assigned_cms: None,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_QUERY_BOUNDED,
        tool_version=CANARY_FIXTURE_VERSION,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert _error_code(body) != "case_not_active"


def test_assigned_effect_journey_disallows_tool(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    _assigned_cms: None,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_ACTION_MEDIUM,
        tool_version=CANARY_FIXTURE_VERSION,
        inputs={"menu_ref": "margherita", "quantity": 1},
    )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "journey_disallows_tool"
    assert _recovery_action(body) != "cms_capture_intent"
    assert "assignment_not_accepted" not in str(response.json())


def test_in_progress_get_menu_still_allows(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_QUERY_BOUNDED,
        tool_version=CANARY_FIXTURE_VERSION,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


def test_in_progress_effect_needs_confirmation(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_ACTION_MEDIUM,
        tool_version=CANARY_FIXTURE_VERSION,
        inputs={"menu_ref": "margherita", "quantity": 1},
    )
    assert response.status_code == 200
    assert_deferred(response.json(), "needs-confirmation")


@pytest.mark.parametrize("status", ["completed", "cancelled", "rejected"])
def test_terminal_bound_tool_is_case_not_active_with_capture(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    status: str,
) -> None:
    async def _get_facts(case_id, *, invoking_subject=None, thread_id=None):
        del case_id, invoking_subject, thread_id
        return build_invoke_facts_for_case_state("closed", status=status)

    with patch(
        _INVOKE_FACTS_PATCH,
        new=AsyncMock(side_effect=_get_facts),
    ):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_QUERY_BOUNDED,
            tool_version=CANARY_FIXTURE_VERSION,
        )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_not_active"
    assert _recovery_action(body) == "cms_capture_intent"


def _live_facts(*, assignee_subject: str, consulting_entitled: bool = False, status: str = "in_progress"):
    async def _get_facts(case_id, *, invoking_subject=None, thread_id=None):
        del case_id, invoking_subject, thread_id
        return build_invoke_facts_response(
            status=status,
            assignee_subject=assignee_subject,
            consulting_entitled=consulting_entitled,
        )

    return patch(_INVOKE_FACTS_PATCH, new=AsyncMock(side_effect=_get_facts))


@pytest.mark.case_identity(production=True)
def test_live_assignee_in_progress_get_menu_succeeds(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    with _live_facts(assignee_subject=de_id):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_QUERY_BOUNDED,
            tool_version=CANARY_FIXTURE_VERSION,
        )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


@pytest.mark.case_identity(production=True)
def test_live_assignee_in_progress_effect_needs_confirmation(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    with _live_facts(assignee_subject=de_id):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_ACTION_MEDIUM,
            tool_version=CANARY_FIXTURE_VERSION,
            inputs={"menu_ref": "margherita", "quantity": 1},
        )
    assert response.status_code == 200
    assert_deferred(response.json(), "needs-confirmation")


@pytest.mark.case_identity(production=True)
def test_live_wrong_subject_is_case_access_revoked(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    with _live_facts(assignee_subject=_OTHER_ASSIGNEE):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_QUERY_BOUNDED,
            tool_version=CANARY_FIXTURE_VERSION,
        )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_access_revoked"
    assert _recovery_action(body) != "cms_capture_intent"


@pytest.mark.case_identity(production=True)
def test_live_consultant_get_menu_with_thread_and_grant_succeeds(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    with _live_facts(assignee_subject=_OTHER_ASSIGNEE, consulting_entitled=True):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_QUERY_BOUNDED,
            tool_version=CANARY_FIXTURE_VERSION,
            thread_id="thread-consult",
            turn_invoke_grant=str(uuid4()),
        )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


@pytest.mark.case_identity(production=True)
def test_live_consultant_effect_is_case_de_not_assignee(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    with _live_facts(assignee_subject=_OTHER_ASSIGNEE, consulting_entitled=True):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_ACTION_MEDIUM,
            tool_version=CANARY_FIXTURE_VERSION,
            inputs={"menu_ref": "margherita", "quantity": 1},
            thread_id="thread-consult",
            turn_invoke_grant=str(uuid4()),
        )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_de_not_assignee"


@pytest.mark.case_identity(production=True)
def test_live_consultant_without_thread_id_is_case_access_revoked(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    with _live_facts(assignee_subject=_OTHER_ASSIGNEE, consulting_entitled=True):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_QUERY_BOUNDED,
            tool_version=CANARY_FIXTURE_VERSION,
            turn_invoke_grant=str(uuid4()),
        )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_access_revoked"


@pytest.mark.case_identity(assignee_subject=_OTHER_ASSIGNEE)
def test_non_assignee_get_menu_is_case_access_revoked(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_QUERY_BOUNDED,
        tool_version=CANARY_FIXTURE_VERSION,
    )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_access_revoked"
    assert _recovery_action(body) != "cms_capture_intent"


@pytest.mark.case_identity(assignee_subject=_OTHER_ASSIGNEE)
def test_non_assignee_effect_is_case_access_revoked(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_ACTION_MEDIUM,
        tool_version=CANARY_FIXTURE_VERSION,
        inputs={"menu_ref": "margherita", "quantity": 1},
    )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_access_revoked"
    assert _recovery_action(body) != "cms_capture_intent"


@pytest.mark.case_identity(assignee_subject=_OTHER_ASSIGNEE, consulting_entitled=True)
def test_consultant_get_menu_with_thread_and_grant_succeeds(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_QUERY_BOUNDED,
        tool_version=CANARY_FIXTURE_VERSION,
        thread_id="thread-consult",
        turn_invoke_grant=str(uuid4()),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


@pytest.mark.case_identity(assignee_subject=_OTHER_ASSIGNEE, consulting_entitled=True)
def test_consultant_effect_is_case_de_not_assignee(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_ACTION_MEDIUM,
        tool_version=CANARY_FIXTURE_VERSION,
        inputs={"menu_ref": "margherita", "quantity": 1},
        thread_id="thread-consult",
        turn_invoke_grant=str(uuid4()),
    )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_de_not_assignee"


@pytest.mark.case_identity(assignee_subject=_OTHER_ASSIGNEE, consulting_entitled=True)
def test_consultant_without_thread_id_is_case_access_revoked(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    response = _invoke(
        client,
        de_id=de_id,
        capability_token=sample_capability_token,
        tool_name=CANARY_QUERY_BOUNDED,
        tool_version=CANARY_FIXTURE_VERSION,
        turn_invoke_grant=str(uuid4()),
    )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "case_access_revoked"


def test_created_read_is_journey_disallowed(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    async def _get_facts(case_id, *, invoking_subject=None, thread_id=None):
        del case_id, invoking_subject, thread_id
        return build_invoke_facts_for_case_state("open", status="created")

    with patch(
        _INVOKE_FACTS_PATCH,
        new=AsyncMock(side_effect=_get_facts),
    ):
        response = _invoke(
            client,
            de_id=de_id,
            capability_token=sample_capability_token,
            tool_name=CANARY_QUERY_BOUNDED,
            tool_version=CANARY_FIXTURE_VERSION,
        )
    assert response.status_code == 403
    body = _deny_body(response)
    assert _error_code(body) == "journey_disallows_tool"
    assert _recovery_action(body) != "cms_capture_intent"


def test_counting_adapter_forwards_kit_kwargs() -> None:
    from tests.host.case_policy_harness import _CountingCaseStateAdapter

    seen: dict[str, object] = {}

    class _Inner:
        async def resolve(self, *, case_id: str, thread_id: str | None = None, invoking_subject: str | None = None):
            seen["case_id"] = case_id
            seen["thread_id"] = thread_id
            seen["invoking_subject"] = invoking_subject
            return CaseStateFacts(exists=True, is_open=True, is_held=False)

    adapter = _CountingCaseStateAdapter(_Inner())

    async def _run() -> None:
        await adapter.resolve(
            case_id="c1",
            thread_id="t1",
            invoking_subject="de-123",
        )

    import asyncio

    asyncio.run(_run())
    assert adapter.resolve_calls == 1
    assert seen == {"case_id": "c1", "thread_id": "t1", "invoking_subject": "de-123"}
