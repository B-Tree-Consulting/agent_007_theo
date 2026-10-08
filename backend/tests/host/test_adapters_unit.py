"""Unit tests for host adapters and capability helpers."""

from __future__ import annotations

import asyncio

import pytest
from bfa.aydeo_host import AydeoHostError, HostErrorCode
from fastapi import HTTPException

from src.config import get_settings
from src.host import adapters as adapters_module
from src.host.adapters import (
    CapabilityValidator,
    ManagementAuthorizer,
    RuntimeIdentityValidator,
    _decode_entra_payload,
    _scopes_from_payload,
)
from src.host.capability_binding import bind_capability_to_de
from src.host.capability import CapabilityToolClaim, VerifiedCapability
from src.host.factory import get_host_blueprint, register_sample_modules
from src.host.request_scope import get_runtime_de_id, set_runtime_request_context
from src.host.runtime_de_outbox import RuntimeDeOutbox
from src.host.testing import capability as cap_module
from src.host.testing.capability import decode_mock_capability_token, mint_mock_capability_token
from src.shared.test_utils import MockIdP, create_de_token
from outbox import InMemoryOutbox
from outbox.models import OutboxEvent
from uuid import uuid4


def test_decode_entra_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    payload = _decode_entra_payload("ignored")
    assert payload["roles"] == ["AyDEO-DE"]


def test_decode_entra_production_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "false")
    get_settings.cache_clear()
    with pytest.raises(AydeoHostError) as exc:
        _decode_entra_payload("token")
    assert exc.value.error.code == HostErrorCode.UNAUTHENTICATED


def test_scopes_from_payload_list() -> None:
    assert _scopes_from_payload({"scope": ["a", "b"]}) == ("a", "b")


def test_scopes_from_payload_scp_string() -> None:
    assert _scopes_from_payload({"scp": "read write"}) == ("read", "write")


def test_management_authorizer_includes_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    token = MockIdP.create_token(
        "mgr",
        roles=["AyDEO-Config-Admin"],
        tid="tenant-123",
    )
    identity = ManagementAuthorizer().authorize(token)
    assert identity.tenant == "tenant-123"


def test_management_authorizer_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    token = MockIdP.create_token("mgr", roles=["AyDEO-User"])
    with pytest.raises(AydeoHostError) as exc:
        ManagementAuthorizer().authorize(token)
    assert exc.value.error.code == HostErrorCode.FORBIDDEN


def test_runtime_validator_missing_de_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    token = MockIdP.create_token("mgr", roles=["AyDEO-Config-Admin"])
    with pytest.raises(AydeoHostError) as exc:
        RuntimeIdentityValidator().validate_entra(token)
    assert exc.value.error.code == HostErrorCode.FORBIDDEN


def test_runtime_validator_missing_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adapters_module,
        "_decode_entra_payload",
        lambda _t: {"roles": ["AyDEO-DE"]},
    )
    with pytest.raises(AydeoHostError) as exc:
        RuntimeIdentityValidator().validate_entra("x")
    assert exc.value.error.code == HostErrorCode.FORBIDDEN


def test_runtime_validator_includes_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adapters_module,
        "_decode_entra_payload",
        lambda _t: {"roles": ["AyDEO-DE"], "sub": "de-1", "tid": "tenant-456"},
    )
    identity = RuntimeIdentityValidator().validate_entra("x")
    assert identity.tenant == "tenant-456"
    assert identity.subject == "de-1"
    assert identity.attrs.get("de_id") is None


def test_capability_validator_production_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "false")
    get_settings.cache_clear()
    validator = CapabilityValidator()

    async def _run() -> None:
        with pytest.raises(AydeoHostError) as exc:
            await validator.validate_capability("cap")
        assert exc.value.error.code == HostErrorCode.UNAUTHENTICATED

    asyncio.run(_run())


def test_capability_validator_binding_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    de_token = create_de_token(get_settings().bfa_test_de_id)
    wrong_cap = mint_mock_capability_token(
        "00000000-0000-4000-8000-000000000099",
        [{"tool_name": "canary_query_bounded", "version": "1.0.0", "risk": "low"}],
    )
    validator = CapabilityValidator()

    async def _run() -> None:
        with set_runtime_request_context(entra_token=de_token):
            with pytest.raises(AydeoHostError) as exc:
                await validator.validate_capability(wrong_cap)
            assert exc.value.error.code == HostErrorCode.POLICY_DENIED

    asyncio.run(_run())


def test_capability_validator_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    de_id = get_settings().bfa_test_de_id
    de_token = create_de_token(de_id)
    cap = mint_mock_capability_token(
        de_id,
        [{"tool_name": "canary_query_bounded", "version": "1.0.0", "risk": "low"}],
    )
    validator = CapabilityValidator()

    async def _run() -> None:
        with set_runtime_request_context(entra_token=de_token):
            claims = await validator.validate_capability(cap)
        assert claims.subject == de_id
        assert claims.de_id == de_id
        assert len(claims.tools) == 1

    asyncio.run(_run())


def test_capability_validator_without_entra_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    jwt_sub = "11111111-1111-4111-8111-111111111111"
    audit_de = "22222222-2222-4222-8222-222222222222"
    cap = mint_mock_capability_token(
        audit_de,
        [{"tool_name": "canary_query_bounded", "version": "1.0.0", "risk": "low"}],
        sub=jwt_sub,
    )
    validator = CapabilityValidator()

    async def _run() -> None:
        claims = await validator.validate_capability(cap)
        assert claims.subject == jwt_sub
        assert claims.de_id == audit_de

    asyncio.run(_run())


def test_capability_validator_de_id_differs_from_entra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    entra = get_settings().bfa_test_de_id
    audit_de = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    de_token = create_de_token(entra)
    cap = mint_mock_capability_token(
        audit_de,
        [{"tool_name": "canary_query_bounded", "version": "1.0.0", "risk": "low"}],
        sub=entra,
    )
    validator = CapabilityValidator()

    async def _run() -> None:
        with set_runtime_request_context(entra_token=de_token):
            claims = await validator.validate_capability(cap)
            assert claims.de_id == audit_de
            assert claims.subject == entra
            assert get_runtime_de_id() == audit_de

    asyncio.run(_run())


def test_capability_de_id_stamps_outbox_not_entra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mint → validate → stored stamp. Wrapper set_runtime_de_id() alone is not this proof."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    entra = get_settings().bfa_test_de_id
    audit_de = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    assert audit_de != entra
    de_token = create_de_token(entra)
    cap = mint_mock_capability_token(
        audit_de,
        [{"tool_name": "canary_query_bounded", "version": "1.0.0", "risk": "low"}],
        sub=entra,
    )
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = OutboxEvent(
        digital_employee_id="00000000-0000-0000-0000-000000000000",
        action_domain="example",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        with set_runtime_request_context(entra_token=de_token):
            claims = await CapabilityValidator().validate_capability(cap)
            assert claims.de_id == audit_de
            assert claims.subject == entra
            await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].digital_employee_id == audit_de


def test_capability_missing_de_id_does_not_substitute_entra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    get_settings.cache_clear()
    entra = get_settings().bfa_test_de_id
    de_token = create_de_token(entra)
    cap = mint_mock_capability_token(
        "",
        [{"tool_name": "canary_query_bounded", "version": "1.0.0", "risk": "low"}],
        sub=entra,
        include_de_id=False,
    )
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = OutboxEvent(
        digital_employee_id="00000000-0000-0000-0000-000000000000",
        action_domain="example",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        with set_runtime_request_context(entra_token=de_token):
            claims = await CapabilityValidator().validate_capability(cap)
            assert claims.de_id is None
            assert claims.subject == entra
            assert get_runtime_de_id() is None
            await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].digital_employee_id is None


def test_bind_capability_to_de_match() -> None:
    verified = VerifiedCapability(
        subject="same",
        de_id="different-audit-id",
        bfa_service_id="s",
        bfa_service_slug="slug",
        tools=(CapabilityToolClaim("t", "1.0.0", "low"),),
    )

    async def _run() -> None:
        await bind_capability_to_de(verified, entra_token="tok", entra_subject="same")

    asyncio.run(_run())


def test_bind_capability_to_de_mismatch() -> None:
    verified = VerifiedCapability(
        subject="a",
        de_id="a",
        bfa_service_id="s",
        bfa_service_slug="slug",
        tools=(CapabilityToolClaim("t", "1.0.0", "low"),),
    )

    async def _run() -> None:
        with pytest.raises(HTTPException) as exc:
            await bind_capability_to_de(verified, entra_token="tok", entra_subject="b")
        assert exc.value.status_code == 403

    asyncio.run(_run())


def test_decode_mock_capability_skips_malformed_jwt_claims() -> None:
    """Malformed JWT tool claims are skipped; legacy .confirm suffix is a defensive guard."""
    de_id = get_settings().bfa_test_de_id
    token = mint_mock_capability_token(
        de_id,
        [
            {"name": "canary_query_bounded", "version": "1.0.0", "risk": "low"},
            {"tool_name": "no-version", "risk": "low"},
            "bad",
            {"tool_name": "x.confirm", "version": "1.0.0", "risk": "low"},
        ],
    )
    verified = decode_mock_capability_token(token)
    assert len(verified.tools) == 1
    assert verified.subject == de_id
    assert verified.de_id == de_id


def test_decode_mock_capability_does_not_fallback_de_id_to_sub() -> None:
    entra = get_settings().bfa_test_de_id
    token = mint_mock_capability_token(
        "ignored-when-omitted",
        [{"tool_name": "canary_query_bounded", "version": "1.0.0", "risk": "low"}],
        sub=entra,
        include_de_id=False,
    )
    verified = decode_mock_capability_token(token)
    assert verified.subject == entra
    assert verified.de_id == ""


def test_catalog_tools_for_mock_capability_includes_valid_entries() -> None:
    tools = cap_module.catalog_tools_for_mock_capability(
        [{"name": "canary_action_direct", "version": "1.0.0", "risk": "medium"}],
    )
    assert tools == [{"tool_name": "canary_action_direct", "version": "1.0.0", "risk": "medium"}]


def test_catalog_tools_for_mock_capability_skips_missing_name() -> None:
    tools = cap_module.catalog_tools_for_mock_capability(
        [{"version": "1.0.0"}, {"name": "b", "version": "1.0.0", "risk": "low"}],
    )
    assert tools == [{"tool_name": "b", "version": "1.0.0", "risk": "low"}]


def test_catalog_tools_for_mock_capability_skips_missing_version() -> None:
    tools = cap_module.catalog_tools_for_mock_capability(
        [{"name": "a"}, {"name": "b", "version": "1.0.0", "risk": "high"}],
    )
    assert tools == [{"tool_name": "b", "version": "1.0.0", "risk": "high"}]


@pytest.mark.no_host_canaries
def test_register_sample_modules_registers_domain_tools() -> None:
    from src.config import get_settings
    from src.host.facade import get_host_bfa
    from tests.host.canary_host_tools import sample_domain_bootstrap_present

    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    register_sample_modules()
    if sample_domain_bootstrap_present():
        names = {entry["name"] for entry in get_host_bfa().catalog()}
        assert names
        return
    with pytest.raises(RuntimeError, match="no registered tools"):
        get_host_bfa()


def test_get_host_bfa_rebuilds_stale_empty_cached_facade() -> None:
    """Kit binds tools at construction; rebuild if a too-early cached facade is empty."""
    from unittest.mock import MagicMock, patch

    from src.host.facade import get_host_bfa

    empty_facade = MagicMock()
    empty_facade.tools.return_value = {}
    full_facade = MagicMock()
    full_facade.tools.return_value = {"canary_query_bounded": object()}

    get_host_bfa.cache_clear()
    try:
        with patch("src.host.facade._get_host_bfa_cached", side_effect=[empty_facade, full_facade]) as mock_cached, patch(
            "src.host.facade._get_host_bfa_cached.cache_clear",
        ) as mock_cache_clear:
            facade = get_host_bfa()
            assert facade is full_facade
            assert mock_cached.call_count == 2
            mock_cache_clear.assert_called_once()
    finally:
        get_host_bfa.cache_clear()


def test_factory_old_agentstepkit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as metadata

    get_host_blueprint.cache_clear()

    def _old_version(_name: str) -> str:
        return "0.1.0"

    monkeypatch.setattr(metadata, "version", _old_version)
    with pytest.raises(ImportError):
        get_host_blueprint()
    get_host_blueprint.cache_clear()


def test_factory_agentstepkit_0_2_24_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as metadata

    get_host_blueprint.cache_clear()

    def _stale_pin(_name: str) -> str:
        return "0.2.24"

    monkeypatch.setattr(metadata, "version", _stale_pin)
    with pytest.raises(ImportError, match="0.2.24"):
        get_host_blueprint()
    get_host_blueprint.cache_clear()


def test_factory_agentstepkit_0_2_25_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as metadata

    get_host_blueprint.cache_clear()

    def _stale_pin(_name: str) -> str:
        return "0.2.25"

    monkeypatch.setattr(metadata, "version", _stale_pin)
    with pytest.raises(ImportError, match="0.2.25"):
        get_host_blueprint()
    get_host_blueprint.cache_clear()


def test_factory_agentstepkit_0_2_26_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as metadata

    from src.host.factory import _ensure_agentstepkit_version

    def _stale_pin(_name: str) -> str:
        return "0.2.26"

    monkeypatch.setattr(metadata, "version", _stale_pin)
    with pytest.raises(ImportError, match="0.2.26"):
        _ensure_agentstepkit_version()


def test_factory_agentstepkit_0_2_27_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as metadata

    from src.host.factory import _ensure_agentstepkit_version

    def _current_pin(_name: str) -> str:
        return "0.2.27"

    monkeypatch.setattr(metadata, "version", _current_pin)
    _ensure_agentstepkit_version()


def test_factory_constructs_case_state_adapter_without_kwargs() -> None:
    import inspect
    from unittest.mock import patch

    from src.host.case_state_adapter import AydeoCaseStateAdapter

    params = inspect.signature(AydeoCaseStateAdapter.__init__).parameters
    assert "identity" not in params

    seen: dict[str, object] = {}
    real = AydeoCaseStateAdapter

    def _capturing(*args: object, **kwargs: object) -> AydeoCaseStateAdapter:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return real(*args, **kwargs)

    get_host_blueprint.cache_clear()
    try:
        with patch("src.host.factory.AydeoCaseStateAdapter", _capturing):
            get_host_blueprint()
        assert seen["args"] == ()
        assert seen["kwargs"] == {}
    finally:
        get_host_blueprint.cache_clear()


def test_factory_parse_version_short_segments() -> None:
    from src.host.factory import _parse_version_tuple

    assert _parse_version_tuple("1") == (1, 0, 0)
def test_unused_token_introspector_raises() -> None:
    from src.host.facade import _UnusedTokenIntrospector

    with pytest.raises(RuntimeError):
        _UnusedTokenIntrospector().introspect("t")


def test_set_runtime_request_context_without_token() -> None:
    from src.host.request_scope import get_runtime_request_scope

    with set_runtime_request_context():
        assert get_runtime_request_scope().entra_token is None
        assert get_runtime_request_scope().correlation_id is None
