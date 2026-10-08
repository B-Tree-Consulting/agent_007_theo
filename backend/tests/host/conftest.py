"""Shared fixtures for host HTTP tests."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.host.case_state_adapter import AydeoCaseStateAdapter
from src.host.facade import get_host_bfa
from src.host.factory import get_host_blueprint
from src.host.testing.capability import (
    catalog_tools_for_mock_capability,
    mint_mock_capability_token,
)
from src.main import app
from tests.host.canary_host_tools import (
    clear_host_caches,
    host_canaries_installed,
    sample_domain_bootstrap_present,
    register_host_canary_tools,
    unregister_host_canary_tools,
)
from tests.host.case_identity_wrapper import CaseIdentityOverlay, wrap_case_state_adapter
from tests.host.cms_fixtures import build_invoke_facts_response, default_open_case_id
from tests.host.platform_adapter_mocks import build_test_platform_adapters


@pytest.fixture(autouse=True)
def _host_canaries_when_sample_absent(request: pytest.FixtureRequest) -> None:
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


@pytest.fixture
def host_canaries() -> None:
    with host_canaries_installed():
        yield


@pytest.fixture(autouse=True)
def _patch_test_platform_adapters() -> None:
    with patch(
        "bfa.aydeo_host.platform.factory.build_platform_adapters",
        return_value=build_test_platform_adapters(),
    ):
        yield


@pytest.fixture
def recorded_case_comments() -> list[dict[str, str]]:
    return []


@pytest.fixture(autouse=True)
def _stub_case_comment_posts(recorded_case_comments: list[dict[str, str]]) -> None:
    """Confirm must not call a live CMS. Tests read `recorded_case_comments`."""

    async def _add(self: object, *, case_id: str, body: str) -> None:
        recorded_case_comments.append(
            {
                "case_id": case_id,
                "body": body,
                "bearer": str(getattr(self, "_bearer", "")),
            }
        )

    with patch("src.host.case_comment_client.CaseCommentClient.add_comment", new=_add):
        yield


@pytest.fixture(autouse=True)
def _mock_open_case_cms() -> None:
    async def _get_invoke_facts(case_id, *, invoking_subject=None, thread_id=None):
        del case_id, invoking_subject, thread_id
        return build_invoke_facts_response()

    with patch(
        "src.host.case_state_adapter.AydeoCmsInternalClient.get_case_invoke_facts",
        new=AsyncMock(side_effect=_get_invoke_facts),
    ):
        yield


@pytest.fixture
def open_case_id() -> str:
    return default_open_case_id()


@pytest.fixture
def case_identity_overlay(request: pytest.FixtureRequest) -> CaseIdentityOverlay | None:
    marker = request.node.get_closest_marker("case_identity")
    if marker is not None and marker.kwargs.get("production"):
        return None
    assignee = get_settings().bfa_test_de_id
    consulting = False
    if marker is not None:
        assignee = marker.kwargs.get("assignee_subject", assignee)
        consulting = bool(marker.kwargs.get("consulting_entitled", False))
    return CaseIdentityOverlay(assignee_subject=assignee, consulting_entitled=consulting)


@pytest.fixture
def client(case_identity_overlay: CaseIdentityOverlay | None) -> TestClient:
    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    get_host_blueprint.cache_clear()
    if case_identity_overlay is None:
        factory_patch: object = nullcontext()
    else:
        overlay = case_identity_overlay

        def _ctor(*args: object, **kwargs: object) -> object:
            return wrap_case_state_adapter(AydeoCaseStateAdapter(*args, **kwargs), overlay)

        factory_patch = patch("src.host.factory.AydeoCaseStateAdapter", _ctor)
    with factory_patch:
        with TestClient(app) as test_client:
            yield test_client
    get_host_blueprint.cache_clear()
    get_host_bfa.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def de_id() -> str:
    return get_settings().bfa_test_de_id


@pytest.fixture
def sample_capability_token(de_id: str) -> str:
    from src.host.facade import HostSampleBFA
    from src.host.factory import register_sample_modules

    if not sample_domain_bootstrap_present():
        register_host_canary_tools(HostSampleBFA)
        clear_host_caches()
    register_sample_modules()
    facade = get_host_bfa()
    catalog = facade.catalog()
    tools = catalog_tools_for_mock_capability(catalog, code_tools=facade.tools())
    return mint_mock_capability_token(de_id, tools)
