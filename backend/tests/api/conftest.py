"""Canaries for HTTP tests in generated clean hosts (pizza bootstrap absent)."""

from __future__ import annotations

import pytest

from tests.host.canary_host_tools import (
    clear_host_caches,
    sample_domain_bootstrap_present,
    register_host_canary_tools,
    unregister_host_canary_tools,
)


@pytest.fixture(autouse=True)
def _api_host_canaries_when_sample_absent(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("no_host_canaries"):
        yield
        return
    if sample_domain_bootstrap_present():
        yield
        return
    from src.host.facade import HostSampleBFA

    register_host_canary_tools(HostSampleBFA)
    clear_host_caches()
    try:
        yield
    finally:
        unregister_host_canary_tools(HostSampleBFA)
        clear_host_caches()
