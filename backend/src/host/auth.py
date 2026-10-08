"""JWT validation for BFA host HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import get_settings
from src.shared.auth import AuthContext, get_current_user

security = HTTPBearer(auto_error=False)

BFA_CATALOG_MODE_MANAGEMENT = "management"
BFA_CATALOG_MODE_RUNTIME = "runtime"


@dataclass(frozen=True)
class BfaCatalogAccess:
    token: str
    mode: str
    auth_ctx: AuthContext
    de_id: str | None = None

    @property
    def is_management(self) -> bool:
        return self.mode == BFA_CATALOG_MODE_MANAGEMENT


@dataclass(frozen=True)
class BfaRuntimeAccess:
    token: str
    auth_ctx: AuthContext
    de_id: str


async def _require_bearer_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> tuple[AuthContext, str]:
    auth_ctx = await get_current_user(request, credentials)
    token = auth_ctx.access_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_ctx, token


def _validated_de_id_from_auth_context(auth_ctx: AuthContext) -> str:
    de_id = str(auth_ctx.subject or "").strip()
    if not de_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BFA runtime requires a validated DE identity subject",
        )
    return de_id


async def require_catalog_bearer(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> BfaCatalogAccess:
    settings = get_settings()
    if not settings.auth_enabled:
        auth_ctx = await get_current_user(request, credentials)
        return BfaCatalogAccess(
            token=auth_ctx.access_token or "",
            mode=BFA_CATALOG_MODE_RUNTIME,
            auth_ctx=auth_ctx,
            de_id=_validated_de_id_from_auth_context(auth_ctx),
        )
    # Production auth is validated by Blueprint/kit adapters.
    # Here we only require the bearer token and let Blueprint decide whether the token is
    # management or runtime (or reject it).
    auth_ctx, token = await _require_bearer_token(request, credentials)
    return BfaCatalogAccess(
        token=token,
        mode=BFA_CATALOG_MODE_RUNTIME,
        auth_ctx=auth_ctx,
        de_id=auth_ctx.subject,
    )


async def require_runtime_bearer(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> BfaRuntimeAccess:
    settings = get_settings()
    if not settings.auth_enabled:
        auth_ctx = await get_current_user(request, credentials)
        return BfaRuntimeAccess(
            token=auth_ctx.access_token or "",
            auth_ctx=auth_ctx,
            de_id=_validated_de_id_from_auth_context(auth_ctx),
        )
    auth_ctx, token = await _require_bearer_token(request, credentials)
    # Blueprint/kit runtime identity validator enforces DE role + subject.
    return BfaRuntimeAccess(
        token=token,
        auth_ctx=auth_ctx,
        de_id=str(auth_ctx.subject or "").strip() or "unknown",
    )


async def require_readiness_access(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return
    # Token presence only; Blueprint readiness call will validate management privileges.
    await _require_bearer_token(request, credentials)
