"""Wire AydeoHostBlueprint for the BFA host sample."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from functools import lru_cache

from bfa.aydeo_host import AydeoHostBlueprint, HostConfig
from bfa.aydeo_host.platform.factory import build_aydeo_host
from bfa.aydeo_host.platform.settings import AydeoPlatformSettings

from src.config import get_settings, parse_entra_api_guid_from_audience_string
from src.host.case_state_adapter import AydeoCaseStateAdapter
from src.host.catalog_scope import build_catalog_scope
from src.host.facade import get_host_bfa
from src.shared.bfa_capability_contract import CAPABILITY_HEADER

_MIN_AGENTSTEPKIT = (0, 2, 27)


@dataclass(frozen=True)
class _PlatformInputs:
    entra_tenant: str
    entra_audience: str
    capability_jwks_url: str
    capability_issuer: str
    chat_base_url: str
    chat_internal_token: str
    approval_proof_jwks_url: str
    approval_proof_issuer: str


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for segment in version.split(".")[:3]:
        digits = "".join(ch for ch in segment if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _ensure_agentstepkit_version() -> None:
    installed = _parse_version_tuple(importlib.metadata.version("agentstepkit"))
    if installed < _MIN_AGENTSTEPKIT:
        raise ImportError(
            f"agentstepkit {importlib.metadata.version('agentstepkit')} is too old "
            f"(need >={'.'.join(str(p) for p in _MIN_AGENTSTEPKIT)})"
        )


def _extract_entra_tenant_from_issuer(issuer: str) -> str | None:
    raw = (issuer or "").strip()
    if not raw:
        return None
    marker = "login.microsoftonline.com/"
    idx = raw.find(marker)
    if idx < 0:
        return None
    remainder = raw[idx + len(marker) :]
    tenant = remainder.split("/")[0].strip()
    return tenant or None


def _resolve_platform_inputs() -> _PlatformInputs:
    settings = get_settings()

    tenant = _extract_entra_tenant_from_issuer(settings.idp_issuer or "")
    if not tenant:
        raise ValueError("Production mode requires IDP_ISSUER with a concrete Entra tenant id in the URL")

    audience = (settings.idp_audience or "").strip()
    if not audience:
        raise ValueError("Production mode requires IDP_AUDIENCE (Entra API audience)")

    cap_jwks = (settings.dris_capability_jwks_uri or "").strip()
    cap_iss = (settings.dris_capability_issuer or "").strip()
    if not cap_jwks or not cap_iss:
        raise ValueError("Production mode requires DRIS_CAPABILITY_JWKS_URI and DRIS_CAPABILITY_ISSUER")

    chat_base = (settings.aydeo_chat_base_url or "").strip()
    chat_token = (settings.aydeo_chat_internal_token or "").strip()
    if not chat_base:
        raise ValueError("Production mode requires AYDEO_CHAT_BASE_URL")
    if not chat_token:
        raise ValueError(
            "Production mode requires AYDEO_CHAT_INTERNAL_TOKEN (or OUTBOX_INTERNAL_SERVICE_TOKEN alias)",
        )

    proof_jwks = (settings.aydeo_platform_approval_proof_jwks_url or "").strip()
    proof_iss = (settings.aydeo_platform_approval_proof_issuer or "").strip()
    if not proof_jwks or not proof_iss:
        raise ValueError("Production mode requires AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL and AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER")

    cms_base = (settings.aydeo_cms_base_url or "").strip()
    if not cms_base:
        raise ValueError("Production mode requires AYDEO_CMS_BASE_URL")

    return _PlatformInputs(
        entra_tenant=tenant,
        entra_audience=audience,
        capability_jwks_url=cap_jwks,
        capability_issuer=cap_iss,
        chat_base_url=chat_base,
        chat_internal_token=chat_token,
        approval_proof_jwks_url=proof_jwks,
        approval_proof_issuer=proof_iss,
    )


def register_sample_modules() -> None:
    """Register domain modules before the host facade is constructed."""
    from src.host.facade import HostSampleBFA, _get_host_bfa_cached
    from src.samples.hello.bootstrap import register_hello_tools

    if register_hello_tools(HostSampleBFA):
        # BFA binds class tool specs at construction; drop a stale empty cached instance.
        _get_host_bfa_cached.cache_clear()

def warm_host_on_startup() -> None:
    """Eagerly register tools and cache host singletons before serving HTTP traffic."""
    get_host_blueprint()
    if not get_host_bfa().tools():
        raise RuntimeError(
            "Host startup warm-up failed: BFA facade has no tools after sample bootstrap",
        )


def _finite_derived_api_audiences_from_guid(guid: str) -> list[str]:
    """Match aydeo-be ``live_resolve_aydeo_entra_config`` finite JWT API audience set."""
    g = (guid or "").strip()
    if not g:
        return []
    gl = g.lower()
    out: list[str] = []
    for candidate in (
        g,
        gl,
        g.upper(),
        f"api://{gl}",
        f"api://{gl}/access_as_user",
        f"api://{gl}/.default",
    ):
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def _entra_audiences_for_platform(settings) -> list[str]:
    """
    Build management/runtime Entra audiences accepted by this host.

    Aligns with the AyDEO platform API so forwarded Config Admin tokens from discover
    validate when ``aud`` is ``api://{app_id}/access_as_user`` (common SPA scope).
    """
    audiences: list[str] = []
    resolved = settings._resolved_aydeo_entra_api_client_id
    if resolved is not None:
        for candidate in _finite_derived_api_audiences_from_guid(str(resolved)):
            if candidate not in audiences:
                audiences.append(candidate)

    raw_audience = (settings.idp_audience or "").strip()
    for part in (segment.strip() for segment in raw_audience.split(",") if segment.strip()):
        if part not in audiences:
            audiences.append(part)
        guid = parse_entra_api_guid_from_audience_string(part)
        if guid is not None:
            for candidate in _finite_derived_api_audiences_from_guid(str(guid)):
                if candidate not in audiences:
                    audiences.append(candidate)
    return audiences


def _dummy_platform_settings(settings) -> AydeoPlatformSettings:
    # Kit settings extra=forbid and env_file=".env"; do not ingest host dotenv keys.
    return AydeoPlatformSettings(
        _env_file=None,
        service_slug=settings.bfa_service_slug,
        service_version=settings.service_version,
        mgmt_audiences=["test-audience"],
        runtime_audiences=["test-audience"],
        mgmt_tenant="test-tenant",
        runtime_tenant="test-tenant",
        capability_jwks_url="http://localhost/.well-known/capability-jwks.json",
        capability_issuer="sample.capability",
        capability_audiences=["aydeo-bfa"],
        chat_base_url="http://localhost:8001",
        chat_internal_token="sample-internal",
        approval_proof_jwks_url="http://localhost/.well-known/approval-proof-jwks.json",
        approval_proof_issuer="sample.approval-proof",
    )


def _host_config(settings) -> HostConfig:
    return HostConfig(
        service_name=settings.bfa_service_slug,
        service_version=settings.service_version,
        capability_header=CAPABILITY_HEADER.lower(),
        confirm_test_mode=settings.bfa_confirm_test_mode,
        invoke_diagnostic_mode=settings.invoke_diagnostic_mode,
    )


def _catalog_scope_for_host() -> object:
    register_sample_modules()
    tool_names = frozenset(get_host_bfa().tools().keys())
    return build_catalog_scope(tool_names)


def _assemble_host_blueprint() -> AydeoHostBlueprint:
    _ensure_agentstepkit_version()
    register_sample_modules()
    settings = get_settings()

    catalog_scope = _catalog_scope_for_host()
    case_state_adapter = AydeoCaseStateAdapter()
    host_config = _host_config(settings)

    if settings.auth_enabled and not settings.auth_test_mode:
        platform = _resolve_platform_inputs()
        entra_audiences = _entra_audiences_for_platform(settings)
        platform_settings = AydeoPlatformSettings(
            _env_file=None,
            service_slug=settings.bfa_service_slug,
            service_version=settings.service_version,
            mgmt_audiences=entra_audiences,
            runtime_audiences=entra_audiences,
            mgmt_tenant=platform.entra_tenant,
            runtime_tenant=platform.entra_tenant,
            capability_jwks_url=platform.capability_jwks_url,
            capability_issuer=platform.capability_issuer,
            capability_audiences=["aydeo-bfa"],
            chat_base_url=platform.chat_base_url,
            chat_internal_token=platform.chat_internal_token,
            approval_proof_jwks_url=platform.approval_proof_jwks_url,
            approval_proof_issuer=platform.approval_proof_issuer,
            entra_clock_skew_sec=settings.jwt_leeway_seconds,
        )
        return build_aydeo_host(
            bfa=get_host_bfa(),
            settings=platform_settings,
            config=host_config,
            case_state_adapter=case_state_adapter,
            catalog_scope=catalog_scope,
        )

    return build_aydeo_host(
        bfa=get_host_bfa(),
        settings=_dummy_platform_settings(settings),
        config=host_config,
        case_state_adapter=case_state_adapter,
        catalog_scope=catalog_scope,
    )


@lru_cache
def get_host_blueprint() -> AydeoHostBlueprint:
    return _assemble_host_blueprint()
