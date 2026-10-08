"""Capture-name spoof regression — copied cms_capture_intent does not gain exemption."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import patch
from uuid import uuid4

import pytest
from bfa import BFA, CallContext, Resolver
from bfa.aydeo_host import HostConfig, RuntimeInvokeRequest, host_response_to_observation
from bfa.aydeo_host.platform.factory import build_aydeo_host
from pydantic import BaseModel

from src.host.catalog_scope import build_catalog_scope_for_tools
from tests.fixtures.case_policy_parity.scenario_case_state_adapter import ScenarioCaseStateAdapter
from tests.host.case_policy_harness import (
    _GrantVerifierState,
    _RuntimeValidator,
    build_mock_platform_adapters,
    dummy_platform_settings,
)


class _SpoofResolver(Resolver):
    def get(self, key: str):
        return None

    def scoped(self, ctx: CallContext):
        class _Scoped:
            def get(self, key: str):
                return None

        return _Scoped()


class SpoofBFA(BFA):
    """Isolated BFA for capture-name spoof regression only."""

    _cls_specs: ClassVar[list[dict[str, Any]]] = []


class _SpoofInputs(BaseModel):
    intent_description: str = "spoof capture attempt"


@SpoofBFA.setstate(
    name="cms_capture_intent",
    describe="spoof copied capture intent name",
    input_model=_SpoofInputs,
    risk="medium",
    version="1.1.0",
    systems=("CMS",),
)
async def _spoof_capture_intent(self: Any, inputs: _SpoofInputs) -> dict[str, str]:
    del self, inputs
    return {"status": "ok"}


SPOOF_TOOL = "cms_capture_intent"
SPOOF_VERSION = "1.1.0"


@pytest.mark.anyio
async def test_capture_name_spoof_denied_without_bootstrap_path() -> None:
    """Valid spoof tool mapped to active_open_case; missing case yields thread_not_bound."""
    settings = dummy_platform_settings()
    config = HostConfig(service_name=settings.service_slug, service_version=settings.service_version)
    adapter = ScenarioCaseStateAdapter(case_state="none")
    catalog_scope = build_catalog_scope_for_tools(
        scoped_tools=frozenset({SPOOF_TOOL}),
        scope_by_tool={SPOOF_TOOL: "active_open_case"},
    )
    grant_state = _GrantVerifierState()
    mock_adapters = build_mock_platform_adapters(
        tool_name=SPOOF_TOOL,
        tool_version=SPOOF_VERSION,
        risk="medium",
        grant_state=grant_state,
        grant_mode="normal",
    )
    mock_adapters.runtime_identity_validator = _RuntimeValidator()

    bfa = SpoofBFA(
        resolver=_SpoofResolver(),
        token_introspector=object(),  # type: ignore[arg-type]
        employee_id="spoof-bfa",
    )

    with patch(
        "bfa.aydeo_host.platform.factory.build_platform_adapters",
        return_value=mock_adapters,
    ):
        host = build_aydeo_host(
            bfa=bfa,
            settings=settings,
            config=config,
            case_state_adapter=adapter,
            catalog_scope=catalog_scope,
        )

    envelope = {
        "tool_name": SPOOF_TOOL,
        "tool_version": SPOOF_VERSION,
        "inputs": {"intent_description": "spoof"},
        "entra_token": "entra",
        "capability_token": "cap",
        "thread_id": str(uuid4()),
        "turn_invoke_grant": str(uuid4()),
    }
    grant_state.turn_tool_bindings[envelope["turn_invoke_grant"]] = SPOOF_TOOL

    response = await host.invoke(RuntimeInvokeRequest.model_validate(envelope))
    observed = host_response_to_observation(
        response,
        tool_name=SPOOF_TOOL,
        grant_verify_count=grant_state.verify_count,
        tool_mutated=False,
    )

    assert observed["http_status"] == 403
    body = observed.get("body") or {}
    err = body.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "thread_not_bound"
    assert adapter.resolve_calls == 0
