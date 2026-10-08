"""Execute shared_engine parity vectors through build_aydeo_host."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bfa.aydeo_host import (
    AydeoHostError,
    CapabilityClaims,
    CapabilityToolGrant,
    HostConfig,
    HostErrorCode,
    RuntimeIdentity,
    RuntimeInvokeRequest,
    VerifiedInvokeContext,
    host_response_to_observation,
)
from bfa.aydeo_host.platform.factory import build_aydeo_host
from bfa.aydeo_host.platform.settings import AydeoPlatformSettings

from src.host.case_state_adapter import AydeoCaseStateAdapter
from src.host.catalog_scope import build_catalog_scope
from tests.fixtures.case_policy_parity.canary_bfa import fresh_canary_bfa
from tests.fixtures.case_policy_parity.mutation_tracker import reset as reset_mutation
from tests.fixtures.case_policy_parity.scenario_case_state_adapter import (
    ScenarioCaseStateAdapter,
    adapter_from_vector_setup,
)
from tests.host.case_identity_wrapper import CaseIdentityOverlay, wrap_case_state_adapter
from tests.host.case_policy_contract import mapping_for_role_id
from tests.host.cms_fixtures import build_invoke_facts_for_case_state

_HARNESS_IDENTITY = CaseIdentityOverlay(assignee_subject="de-123")


class _RuntimeValidator:
    async def validate_entra(self, token: str, *, correlation_id: str | None = None) -> RuntimeIdentity:
        if token != "entra":
            raise AydeoHostError(HostErrorCode.UNAUTHENTICATED, "invalid Entra DE token")
        return RuntimeIdentity(subject="de-123", scopes=("bfa.invoke",), entra_token=token)


class _CapabilityValidator:
    def __init__(self, tool_name: str, tool_version: str, risk: str) -> None:
        self._claims = CapabilityClaims(
            subject="de-123",
            tools=(
                CapabilityToolGrant(
                    name=tool_name,
                    version=tool_version,
                    effective_risk=risk,  # type: ignore[arg-type]
                ),
            ),
        )

    async def validate_capability(
        self, token: str, *, correlation_id: str | None = None
    ) -> CapabilityClaims:
        if token != "cap":
            raise AydeoHostError(HostErrorCode.UNAUTHENTICATED, "invalid capability token")
        return self._claims


@dataclass
class _GrantVerifierState:
    verify_count: int = 0
    consumed: set[str] = field(default_factory=set)
    turn_tool_bindings: dict[str, str] = field(default_factory=dict)


class _ParityGrantVerifier:
    def __init__(self, state: _GrantVerifierState, *, grant_mode: str = "normal") -> None:
        self._state = state
        self._grant_mode = grant_mode

    async def verify_invoke(
        self,
        request: RuntimeInvokeRequest,
        *,
        tool_name: str,
        grant_kind: str,
        grant: object,
    ) -> VerifiedInvokeContext:
        del grant_kind, grant
        self._state.verify_count += 1
        grant_token = request.turn_invoke_grant or ""
        if self._grant_mode == "replay" or grant_token in self._state.consumed:
            raise AydeoHostError(
                HostErrorCode.POLICY_DENIED,
                "grant already consumed",
                status_code=403,
                details={
                    "chat_error": {
                        "error": {
                            "code": "invoke_grant_already_used",
                            "message": "Grant already consumed",
                        }
                    }
                },
            )
        if self._grant_mode == "invalid":
            raise AydeoHostError(
                HostErrorCode.POLICY_DENIED,
                "invoke grant invalid",
                status_code=403,
                details={
                    "chat_error": {
                        "error": {
                            "code": "invoke_grant_invalid",
                            "message": "invoke_grant_invalid",
                        }
                    }
                },
            )
        bound_tool = self._state.turn_tool_bindings.get(grant_token)
        if bound_tool is not None and bound_tool != tool_name:
            raise AydeoHostError(
                HostErrorCode.POLICY_DENIED,
                "tool binding mismatch",
                status_code=403,
                details={
                    "chat_error": {
                        "error": {
                            "code": "invoke_grant_invalid",
                            "message": "tool_name does not match grant",
                        }
                    }
                },
            )
        self._state.consumed.add(grant_token)
        return VerifiedInvokeContext(attrs={})


class _CountingCaseStateAdapter:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.resolve_calls = 0

    async def resolve(
        self,
        *,
        case_id: str,
        thread_id: str | None = None,
        invoking_subject: str | None = None,
    ):
        self.resolve_calls += 1
        return await self._inner.resolve(
            case_id=case_id,
            thread_id=thread_id,
            invoking_subject=invoking_subject,
        )


def _facts_case_id(case_state: str) -> str | None:
    if case_state in ("open", "closed", "held"):
        return str(uuid4())
    if case_state == "unknown":
        return "11111111-1111-4111-8111-111111111111"
    return None


def dummy_platform_settings() -> AydeoPlatformSettings:
    return AydeoPlatformSettings(
        _env_file=None,
        service_slug="agent-007-theo-canary",
        service_version="canary-1",
        mgmt_audiences=["test-audience"],
        runtime_audiences=["test-audience"],
        mgmt_tenant="test-tenant",
        runtime_tenant="test-tenant",
        capability_jwks_url="http://localhost/.well-known/capability-jwks.json",
        capability_issuer="canary.capability",
        capability_audiences=["aydeo-bfa"],
        chat_base_url="http://localhost:8001",
        chat_internal_token="canary-internal",
        approval_proof_jwks_url="http://localhost/.well-known/approval-proof-jwks.json",
        approval_proof_issuer="canary.approval-proof",
    )


def build_mock_platform_adapters(
    *,
    tool_name: str,
    tool_version: str,
    risk: str,
    grant_state: _GrantVerifierState,
    grant_mode: str,
) -> MagicMock:
    adapters = MagicMock()
    adapters.management_authorizer = object()
    adapters.runtime_identity_validator = _RuntimeValidator()
    adapters.capability_validator = _CapabilityValidator(tool_name, tool_version, risk)
    adapters.invoke_grant_verifier = _ParityGrantVerifier(grant_state, grant_mode=grant_mode)
    adapters.lane_b_confirm_verifier = object()
    return adapters


def _case_adapter_for_vector(setup: dict[str, object]) -> tuple[Any, list[Any]]:
    cms_mode = str(setup.get("cms_mode", "normal"))
    case_state = str(setup.get("case_state", "none"))
    patches: list[Any] = []

    if cms_mode == "hold_fail":
        return _CountingCaseStateAdapter(adapter_from_vector_setup(setup)), patches

    if cms_mode == "scope_fail":
        inner = wrap_case_state_adapter(AydeoCaseStateAdapter(), _HARNESS_IDENTITY)
        adapter = _CountingCaseStateAdapter(inner)

        async def _raise_transport(*_args, **_kwargs):
            raise RuntimeError("cms unavailable")

        patches.append(
            patch(
                "src.host.case_state_adapter.AydeoCmsInternalClient.get_case_invoke_facts",
                new=AsyncMock(side_effect=_raise_transport),
            )
        )
        return adapter, patches

    inner = wrap_case_state_adapter(AydeoCaseStateAdapter(), _HARNESS_IDENTITY)
    adapter = _CountingCaseStateAdapter(inner)

    async def _mock_get_facts(*_args, **_kwargs):
        return build_invoke_facts_for_case_state(case_state)

    patches.append(
        patch(
            "src.host.case_state_adapter.AydeoCmsInternalClient.get_case_invoke_facts",
            new=AsyncMock(side_effect=_mock_get_facts),
        )
    )
    return adapter, patches


async def run_shared_engine_vector(vector: dict[str, Any]) -> dict[str, Any]:
    setup = vector.get("setup") or {}
    role_id = vector["tool_role"]["role_id"]
    mapping = mapping_for_role_id(role_id)
    tool_name = mapping["tool_name"]
    tool_version = mapping["tool_version"]
    risk = mapping["tool_role"]["risk"]

    case_state = setup.get("case_state", "none")
    case_id = _facts_case_id(str(case_state))
    adapter, cms_patches = _case_adapter_for_vector(setup)

    grant_state = _GrantVerifierState()
    grant_mode = setup.get("grant_mode", "normal")

    settings = dummy_platform_settings()
    config = HostConfig(service_name=settings.service_slug, service_version=settings.service_version)
    mock_adapters = build_mock_platform_adapters(
        tool_name=tool_name,
        tool_version=tool_version,
        risk=risk,
        grant_state=grant_state,
        grant_mode=str(grant_mode),
    )

    bfa = fresh_canary_bfa()
    catalog_scope = build_catalog_scope(frozenset(bfa.tools().keys()))

    for cms_patch in cms_patches:
        cms_patch.start()

    try:
        with patch(
            "bfa.aydeo_host.platform.factory.build_platform_adapters",
            return_value=mock_adapters,
        ), patch.dict(
            "os.environ",
            {
                "AYDEO_CMS_BASE_URL": "http://localhost:8000",
                "AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN": "test-internal-token",
            },
            clear=False,
        ):
            from src.config import get_settings

            get_settings.cache_clear()
            host = build_aydeo_host(
                bfa=bfa,
                settings=settings,
                config=config,
                case_state_adapter=adapter,
                catalog_scope=catalog_scope,
            )

        envelope: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_version": tool_version,
            "inputs": dict(mapping.get("default_inputs") or {}),
            "entra_token": "entra",
            "capability_token": "cap",
        }

        caller = setup.get("caller_surface", "headless")
        turn_grant: str | None = None
        if caller == "interactive":
            thread_id = str(uuid4())
            turn_grant = str(uuid4())
            grant_state.turn_tool_bindings[turn_grant] = tool_name
            envelope["thread_id"] = thread_id
            envelope["turn_invoke_grant"] = turn_grant
        elif caller == "interactive_no_grant":
            envelope["thread_id"] = str(uuid4())

        if turn_grant and grant_mode == "tool_mismatch":
            grant_state.turn_tool_bindings[turn_grant] = "get_bound_case_details"
        elif turn_grant and grant_mode == "replay":
            grant_state.consumed.add(turn_grant)

        envelope_case = setup.get("envelope_case_id", "dynamic")
        if envelope_case == "missing":
            pass
        elif envelope_case == "invalid_uuid":
            envelope["case_id"] = "not-a-uuid"
        elif envelope_case == "unknown_uuid":
            envelope["case_id"] = "11111111-1111-4111-8111-111111111111"
        elif envelope_case == "dynamic" and case_id is not None and caller in ("headless", "cms_orchestration"):
            envelope["case_id"] = case_id

        reset_mutation()
        request = RuntimeInvokeRequest.model_validate(envelope)
        from src.host.request_scope import set_runtime_request_context

        with set_runtime_request_context(entra_token="entra"):
            response = await host.invoke(request)

        from tests.fixtures.case_policy_parity import mutation_tracker

        observation = host_response_to_observation(
            response,
            tool_name=tool_name,
            grant_verify_count=grant_state.verify_count,
            tool_mutated=mutation_tracker.mutated,
        )
        observation["adapter_resolve_count"] = adapter.resolve_calls
        return observation
    finally:
        for cms_patch in reversed(cms_patches):
            cms_patch.stop()
        from src.config import get_settings

        get_settings.cache_clear()
