"""Unit tests for parity scenario case-state adapter branches."""

from __future__ import annotations

import pytest

from tests.fixtures.case_policy_parity.scenario_case_state_adapter import (
    ScenarioCaseStateAdapter,
    adapter_from_vector_setup,
)


@pytest.mark.anyio
async def test_resolve_scope_fail_returns_scope_unavailable() -> None:
    adapter = ScenarioCaseStateAdapter(case_state="open", cms_mode="scope_fail")
    facts = await adapter.resolve(case_id="case-1", thread_id="t", invoking_subject="de-123")
    assert facts.dependency_failure == "scope_unavailable"


@pytest.mark.anyio
async def test_resolve_hold_fail_returns_hold_unavailable() -> None:
    adapter = ScenarioCaseStateAdapter(case_state="open", cms_mode="hold_fail")
    facts = await adapter.resolve(case_id="case-1", invoking_subject="de-123")
    assert facts.dependency_failure == "hold_unavailable"
    assert facts.assignee_subject == "de-123"
    assert facts.status == "in_progress"


@pytest.mark.anyio
async def test_resolve_open_emits_authority_facts() -> None:
    adapter = ScenarioCaseStateAdapter(case_state="open")
    facts = await adapter.resolve(case_id="case-1")
    assert facts.is_open is True
    assert facts.assignee_subject == "de-123"
    assert facts.status == "in_progress"


@pytest.mark.anyio
async def test_adapter_from_vector_setup_defaults() -> None:
    adapter = adapter_from_vector_setup({})
    assert adapter._case_state == "none"
    assert adapter._cms_mode == "normal"
