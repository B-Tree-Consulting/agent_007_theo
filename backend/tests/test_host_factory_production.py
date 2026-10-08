"""Production-mode host factory wiring (issue #19)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config import Settings, get_settings
from src.host.factory import (
    _extract_entra_tenant_from_issuer,
    _finite_derived_api_audiences_from_guid,
    _resolve_platform_inputs,
    get_host_blueprint,
)


def _prod_settings_kwargs(**overrides) -> dict:
    base = {
        "database_url": "postgresql://u:p@localhost/db",
        "auth_enabled": True,
        "auth_test_mode": False,
        "idp_issuer": "https://login.microsoftonline.com/tenant-guid/v2.0/",
        "idp_audience": "api://a6dc5888-6677-48b4-a11f-d4065e8af80a",
        "dris_capability_jwks_uri": "http://localhost:8000/.well-known/bfa-capability-jwks.json",
        "dris_capability_issuer": "aydeo-be.dris",
        "aydeo_chat_base_url": "http://localhost:8001",
        "aydeo_chat_internal_token": "chat-internal",
        "aydeo_platform_approval_proof_jwks_url": "http://localhost:8000/.well-known/approval-proof-jwks.json",
        "aydeo_platform_approval_proof_issuer": "aydeo-be.approval-proof",
        "aydeo_cms_base_url": "http://localhost:8000",
    }
    base.update(overrides)
    return base


def _apply_prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _prod_settings_kwargs().items():
        env_key = {
            "database_url": "DATABASE_URL",
            "auth_enabled": "AUTH_ENABLED",
            "auth_test_mode": "AUTH_TEST_MODE",
            "idp_issuer": "IDP_ISSUER",
            "idp_audience": "IDP_AUDIENCE",
            "dris_capability_jwks_uri": "DRIS_CAPABILITY_JWKS_URI",
            "dris_capability_issuer": "DRIS_CAPABILITY_ISSUER",
            "aydeo_chat_base_url": "AYDEO_CHAT_BASE_URL",
            "aydeo_chat_internal_token": "AYDEO_CHAT_INTERNAL_TOKEN",
            "aydeo_platform_approval_proof_jwks_url": "AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL",
            "aydeo_platform_approval_proof_issuer": "AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER",
            "aydeo_cms_base_url": "AYDEO_CMS_BASE_URL",
        }[key]
        monkeypatch.setenv(env_key, str(value).lower() if isinstance(value, bool) else str(value))
    monkeypatch.setenv("APP_ID", "a6dc5888-6677-48b4-a11f-d4065e8af80a")
    get_settings.cache_clear()


_ENV_OVERRIDES = {
    "idp_issuer": "IDP_ISSUER",
    "idp_audience": "IDP_AUDIENCE",
    "dris_capability_jwks_uri": "DRIS_CAPABILITY_JWKS_URI",
    "dris_capability_issuer": "DRIS_CAPABILITY_ISSUER",
    "aydeo_platform_approval_proof_jwks_url": "AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL",
    "aydeo_platform_approval_proof_issuer": "AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER",
    "aydeo_chat_base_url": "AYDEO_CHAT_BASE_URL",
    "aydeo_chat_internal_token": "AYDEO_CHAT_INTERNAL_TOKEN",
    "aydeo_cms_base_url": "AYDEO_CMS_BASE_URL",
}


@pytest.mark.parametrize(
    ("issuer", "expected"),
    [
        ("", None),
        ("https://example.com/tenant", None),
        ("https://login.microsoftonline.com//v2.0/", None),
        (
            "https://login.microsoftonline.com/717a524d-f07a-42ed-acf5-1a76221f1bec/v2.0/",
            "717a524d-f07a-42ed-acf5-1a76221f1bec",
        ),
    ],
)
def test_extract_entra_tenant_from_issuer(issuer: str, expected: str | None) -> None:
    assert _extract_entra_tenant_from_issuer(issuer) == expected


def test_finite_derived_api_audiences_empty_guid() -> None:
    assert _finite_derived_api_audiences_from_guid("") == []
    assert _finite_derived_api_audiences_from_guid("   ") == []


def test_resolve_platform_inputs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_prod_env(monkeypatch)
    inputs = _resolve_platform_inputs()
    assert inputs.entra_tenant == "tenant-guid"
    assert inputs.capability_issuer == "aydeo-be.dris"
    assert inputs.chat_internal_token == "chat-internal"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"idp_issuer": "https://example.com/"}, "IDP_ISSUER"),
        ({"idp_audience": ""}, "IDP_AUDIENCE"),
        ({"dris_capability_jwks_uri": ""}, "DRIS_CAPABILITY"),
        ({"aydeo_platform_approval_proof_jwks_url": ""}, "APPROVAL_PROOF"),
        ({"aydeo_chat_base_url": ""}, "AYDEO_CHAT_BASE_URL"),
        ({"aydeo_chat_internal_token": ""}, "AYDEO_CHAT_INTERNAL_TOKEN"),
        ({"aydeo_cms_base_url": ""}, "AYDEO_CMS_BASE_URL"),
    ],
)
def test_resolve_platform_inputs_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict,
    match: str,
) -> None:
    _apply_prod_env(monkeypatch)
    for key, value in overrides.items():
        monkeypatch.setenv(_ENV_OVERRIDES[key], value)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match=match):
        _resolve_platform_inputs()


def test_get_host_blueprint_production_uses_platform_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_prod_env(monkeypatch)
    get_host_blueprint.cache_clear()

    mock_adapters = MagicMock()
    mock_adapters.management_authorizer = object()
    mock_identity = MagicMock(subject="00000000-0000-4000-8000-0000000000de")
    mock_adapters.runtime_identity_validator.validate_entra = MagicMock(
        return_value=mock_identity,
    )
    mock_adapters.capability_validator = object()
    mock_adapters.invoke_grant_verifier = object()
    mock_adapters.lane_b_confirm_verifier = object()

    with patch("bfa.aydeo_host.platform.factory.build_platform_adapters", return_value=mock_adapters) as build:
        blueprint = get_host_blueprint()

    build.assert_called_once()
    assert blueprint._case_state_adapter is not None
    assert blueprint._case_scope_policy is not None
    assert blueprint._hold_policy is not None
    assert blueprint._management_authorizer is mock_adapters.management_authorizer
    assert blueprint._capability_validator is mock_adapters.capability_validator
    wrapped_validator = blueprint._runtime_identity_validator
    assert wrapped_validator.validate_entra("jwt", correlation_id="corr") is mock_identity
    mock_adapters.runtime_identity_validator.validate_entra.assert_called_once_with(
        "jwt",
        correlation_id="corr",
    )
    get_host_blueprint.cache_clear()
    get_settings.cache_clear()


def test_entra_audiences_skips_duplicate_candidates() -> None:
    guid = "a6dc5888-6677-48b4-a11f-d4065e8af80a"
    settings = Settings(
        **_prod_settings_kwargs(
            aydeo_entra_app_id=guid,
            idp_audience=f"api://{guid},api://{guid}/access_as_user",
        )
    )
    from src.host.factory import _entra_audiences_for_platform

    audiences = _entra_audiences_for_platform(settings)
    assert audiences.count(f"api://{guid}/access_as_user") == 1
