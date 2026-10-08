"""AydeoHostBlueprint protocol adapters."""

from __future__ import annotations

from typing import Tuple

from bfa.aydeo_host import (
    AydeoHostError,
    CapabilityClaims,
    CapabilityToolGrant,
    HostErrorCode,
    ManagementIdentity,
    RuntimeIdentity,
)
from fastapi import HTTPException

from src.config import get_settings
from src.host.capability_binding import bind_capability_to_de
from src.host.request_scope import get_runtime_request_scope, set_runtime_de_id
from src.host.testing.capability import decode_mock_capability_token
from src.shared.auth import ROLE_AYDEO_DE, _resolve_roles
from src.shared.test_utils import MockIdP

BFA_MANAGEMENT_ROLES = frozenset(
    {
        "DRIS-Admin",
        "AyDEO-Config-Admin",
        "DRIS-Organization-Admin",
        "DRIS-Team-Admin",
        "DRIS-Digital-Employee-Admin",
    }
)


def _decode_entra_payload(token: str) -> dict:
    settings = get_settings()
    if not settings.auth_enabled:
        return {
            "sub": settings.bfa_test_de_id,
            "roles": [ROLE_AYDEO_DE],
        }
    if settings.auth_test_mode:
        return MockIdP.decode_without_verification(token)
    raise AydeoHostError(
        HostErrorCode.UNAUTHENTICATED,
        "Production Entra JWKS validation is not wired in this increment",
    )


def _roles_from_payload(payload: dict) -> Tuple[str, ...]:
    return tuple(_resolve_roles(None, payload))


def _scopes_from_payload(payload: dict) -> Tuple[str, ...]:
    scopes_raw = payload.get("scope") or payload.get("scp") or ""
    if isinstance(scopes_raw, list):
        return tuple(str(s) for s in scopes_raw)
    return tuple(s for s in str(scopes_raw).split() if s)


def _identity_subject(payload: dict) -> str:
    return str(payload.get("sub") or payload.get("oid") or "").strip()


class ManagementAuthorizer:
    def authorize(
        self,
        token: str,
        *,
        correlation_id: str | None = None,
    ) -> ManagementIdentity:
        del correlation_id
        payload = _decode_entra_payload(token)
        roles = _roles_from_payload(payload)
        settings = get_settings()
        if settings.auth_enabled and not any(r in BFA_MANAGEMENT_ROLES for r in roles):
            raise AydeoHostError(
                HostErrorCode.FORBIDDEN,
                "BFA management authorization requires an authorized BFA management role",
            )
        tenant_raw = payload.get("tid")
        tenant = str(tenant_raw) if tenant_raw is not None else None
        return ManagementIdentity(
            subject=_identity_subject(payload),
            tenant=tenant,
            roles=roles,
            attrs={"roles": list(roles)},
        )


class RuntimeIdentityValidator:
    def validate_entra(
        self,
        token: str,
        *,
        correlation_id: str | None = None,
    ) -> RuntimeIdentity:
        del correlation_id
        payload = _decode_entra_payload(token)
        roles = _roles_from_payload(payload)
        settings = get_settings()
        if settings.auth_enabled and ROLE_AYDEO_DE not in roles:
            raise AydeoHostError(
                HostErrorCode.FORBIDDEN,
                "BFA invoke requires the AyDEO-DE application role",
            )
        subject = _identity_subject(payload)
        if not subject:
            raise AydeoHostError(
                HostErrorCode.FORBIDDEN,
                "BFA runtime requires a validated DE identity subject",
            )
        tenant_raw = payload.get("tid")
        tenant = str(tenant_raw) if tenant_raw is not None else None
        return RuntimeIdentity(
            subject=subject,
            tenant=tenant,
            roles=roles,
            scopes=_scopes_from_payload(payload),
            entra_token=token,
        )


class CapabilityValidator:
    async def validate_capability(
        self,
        token: str,
        *,
        correlation_id: str | None = None,
    ) -> CapabilityClaims:
        del correlation_id
        settings = get_settings()
        scope = get_runtime_request_scope()
        entra_token = scope.entra_token

        try:
            if settings.auth_test_mode or not settings.auth_enabled:
                verified = decode_mock_capability_token(token)
                identity_sub = ""
                if entra_token:
                    identity_sub = _identity_subject(_decode_entra_payload(entra_token))
                    await bind_capability_to_de(
                        verified,
                        entra_token=entra_token,
                        entra_subject=identity_sub,
                    )
            else:
                raise AydeoHostError(
                    HostErrorCode.UNAUTHENTICATED,
                    "Production capability JWKS validation is not wired in this increment",
                )
        except HTTPException as exc:
            raise AydeoHostError(
                HostErrorCode.POLICY_DENIED,
                str(exc.detail),
                status_code=exc.status_code,
            ) from exc

        grants = tuple(
            CapabilityToolGrant(
                name=claim.tool_name,
                version=claim.version,
                effective_risk=claim.risk,  # type: ignore[arg-type]
            )
            for claim in verified.tools
        )
        de_id = (verified.de_id or "").strip() or None
        capability_subject = (verified.subject or "").strip() or None
        if entra_token:
            capability_subject = identity_sub
        set_runtime_de_id(de_id)
        attrs: dict[str, str] = {
            "bfa_service_id": verified.bfa_service_id,
            "bfa_service_slug": verified.bfa_service_slug,
        }
        if de_id:
            attrs["de_id"] = de_id
        return CapabilityClaims(
            subject=capability_subject,
            de_id=de_id,
            tools=grants,
            attrs=attrs,
        )
