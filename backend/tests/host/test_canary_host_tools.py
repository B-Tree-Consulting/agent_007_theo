"""Isolation for test-only HostSampleBFA canary registration."""

from __future__ import annotations

import pytest

from src.host.facade import HostSampleBFA
from tests.fixtures.case_policy_parity.canary_tools import CANARY_QUERY_BOUNDED
from tests.host.canary_host_tools import (
    register_host_canary_tools,
    unregister_host_canary_tools,
)


@pytest.mark.no_host_canaries
def test_register_teardown_restores_host_sample_bfa_specs() -> None:
    before = list(getattr(HostSampleBFA, "_cls_specs", []) or [])
    register_host_canary_tools(HostSampleBFA)
    names = {spec.get("name") for spec in getattr(HostSampleBFA, "_cls_specs", []) if isinstance(spec, dict)}
    assert CANARY_QUERY_BOUNDED in names or hasattr(HostSampleBFA, CANARY_QUERY_BOUNDED)
    unregister_host_canary_tools(HostSampleBFA)
    after = list(getattr(HostSampleBFA, "_cls_specs", []) or [])
    assert after == before
    # Second register/teardown stays idempotent.
    register_host_canary_tools(HostSampleBFA)
    unregister_host_canary_tools(HostSampleBFA)
    assert list(getattr(HostSampleBFA, "_cls_specs", []) or []) == before
