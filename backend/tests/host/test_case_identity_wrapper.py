"""Test-only overlay wrapper: synthetic facts, never a production seam."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.host.case_state_adapter import AydeoCaseStateAdapter
from tests.host.case_identity_wrapper import CaseIdentityOverlay, wrap_case_state_adapter
from tests.host.cms_fixtures import build_invoke_facts_response


@pytest.mark.anyio
async def test_wrapper_replaces_identity_and_does_not_copy_invoking_subject() -> None:
    case_id = str(uuid4())
    inner = AydeoCaseStateAdapter()
    adapter = wrap_case_state_adapter(
        inner,
        CaseIdentityOverlay(assignee_subject="overlay-de", consulting_entitled=True),
    )
    with patch(
        "src.host.case_state_adapter.AydeoCmsInternalClient.get_case_invoke_facts",
        new=AsyncMock(return_value=build_invoke_facts_response()),
    ):
        facts = await adapter.resolve(
            case_id=case_id,
            thread_id="t1",
            invoking_subject="invoker-de",
        )
    assert facts.assignee_subject == "overlay-de"
    assert facts.consulting_entitled is True
    assert facts.exists is True
    assert facts.status == "in_progress"
