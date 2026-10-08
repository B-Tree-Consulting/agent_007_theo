"""Authentication helpers for the BFA host sample.

Production mode uses Blueprint/kit validators; this module is a thin bearer extractor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import get_settings
from src.shared.test_utils import MockIdP

ROLE_DRIS_ADMIN = "DRIS-Admin"
ROLE_DRIS_ORGANIZATION_ADMIN = "DRIS-Organization-Admin"
ROLE_DRIS_TEAM_ADMIN = "DRIS-Team-Admin"
ROLE_DRIS_DIGITAL_EMPLOYEE_ADMIN = "DRIS-Digital-Employee-Admin"
ROLE_AYDEO_CONFIG_ADMIN = "AyDEO-Config-Admin"
ROLE_AYDEO_DE = "AyDEO-DE"

REGISTERED_ROLE_VALUES = frozenset(
    {
        ROLE_DRIS_ADMIN,
        ROLE_DRIS_ORGANIZATION_ADMIN,
        ROLE_DRIS_TEAM_ADMIN,
        ROLE_DRIS_DIGITAL_EMPLOYEE_ADMIN,
        ROLE_AYDEO_CONFIG_ADMIN,
        ROLE_AYDEO_DE,
    }
)

AYDEO_REGISTERED_ROLES = REGISTERED_ROLE_VALUES

ENTRA_ROLE_CLAIM = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
X_USER_ROLES_HEADER = "X-User-Roles"

security = HTTPBearer(auto_error=False)


def _resolve_bearer_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> str | None:
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
        if token:
            return token
    auth_header = (request.headers.get("authorization") or "").strip()
    if not auth_header:
        return None
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None
    return None


def _resolve_roles(header_roles_raw: Optional[str], payload: dict) -> list[str]:
    if header_roles_raw:
        roles = [r.strip() for r in header_roles_raw.split(",") if r.strip()]
        if roles:
            return roles
    roles = payload.get("roles")
    if isinstance(roles, list) and roles:
        return [str(r) for r in roles]
    if isinstance(roles, str) and roles:
        return [roles.strip()]
    entra = payload.get(ENTRA_ROLE_CLAIM)
    if isinstance(entra, list) and entra:
        return [str(r) for r in entra]
    if isinstance(entra, str) and entra:
        return [entra.strip()]
    return []


@dataclass
class AuthContext:
    subject: str | None
    roles: list[str]
    scopes: list[str]
    token_payload: dict
    access_token: str | None = None

    def __init__(
        self,
        payload: dict,
        *,
        access_token: str | None = None,
    ) -> None:
        self.subject = payload.get("sub")
        self.roles = list(payload.get("roles") or [])
        scope_raw = payload.get("scope") or ""
        if isinstance(scope_raw, list):
            self.scopes = [str(s) for s in scope_raw]
        else:
            self.scopes = [s for s in str(scope_raw).split() if s]
        self.token_payload = payload
        self.access_token = access_token


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> AuthContext:
    settings = get_settings()
    if not settings.auth_enabled:
        return AuthContext(
            {"sub": settings.bfa_test_de_id, "roles": [ROLE_AYDEO_CONFIG_ADMIN], "scope": "*"},
            access_token=None,
        )

    token = _resolve_bearer_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    header_roles = request.headers.get(X_USER_ROLES_HEADER)
    try:
        if settings.auth_test_mode:
            payload = MockIdP.decode_without_verification(token)
        else:
            # Production mode validation happens in AydeoHostBlueprint adapters.
            payload = {}
        roles = _resolve_roles(header_roles, payload)
        return AuthContext({**payload, "roles": roles}, access_token=token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
