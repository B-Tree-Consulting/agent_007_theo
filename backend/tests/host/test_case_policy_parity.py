"""Parameterized shared_engine parity vectors (sample#23 Phase A)."""

from __future__ import annotations

import pytest

from tests.host.case_policy_assertions import assert_semantic_expectation
from tests.host.case_policy_contract import (
    SHARED_ENGINE_VECTOR_IDS,
    load_expected,
    load_vector,
)
from tests.host.case_policy_harness import run_shared_engine_vector


@pytest.mark.anyio
@pytest.mark.parametrize("vector_id", SHARED_ENGINE_VECTOR_IDS)
async def test_shared_engine_vector(vector_id: str) -> None:
    vector = load_vector(vector_id)
    expected = load_expected(vector_id)
    observed = await run_shared_engine_vector(vector)
    assert_semantic_expectation(observed, expected)

    adapter_calls = observed.get("adapter_resolve_count", 0)
    if vector_id in {
        "scope_headless_missing_case_thread_not_bound",
        "scope_interactive_missing_case_thread_not_bound",
        "grant_lane_a_turn_missing",
        "grant_lane_a_turn_invalid",
        "grant_lane_a_tool_mismatch",
        "grant_lane_a_turn_replay",
    }:
        assert adapter_calls == 0, observed
    elif vector_id.startswith(("scope_", "hold_", "ordering_")):
        assert adapter_calls == 1, observed
