"""AyDEO agent-007-theo FastAPI application.

Template core lives under ``src/host/``; removable demo domain under ``src/samples/``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from bfa.aydeo_host import ManagementRequest

from src.config import get_settings
from src.host.api import router as bfa_router
from src.host.auth import require_readiness_access, security
from src.host.factory import get_host_blueprint, warm_host_on_startup
from src.host.http import raise_for_host_response
from src.host.outbox_factory import close_audit_outbox_if_active
from src.shared.auth import _resolve_bearer_token

settings = get_settings()

_level_name = settings.log_level.upper()
if _level_name == "TRACE":
    _level_name = "DEBUG"  # stdlib has no TRACE
logging.basicConfig(
    level=getattr(logging, _level_name, logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    warm_host_on_startup()
    yield
    close_audit_outbox_if_active()


app = FastAPI(
    title="AyDEO agent-007-theo API",
    version=settings.service_version,
    lifespan=_app_lifespan,
    description=(
        "Reference AyDEO BFA host microservice. "
        "Template core: `backend/src/host/`. Removable sample: `backend/src/samples/<domain>/`."
    ),
)

app.include_router(bfa_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    del request
    headers = dict(exc.headers) if exc.headers else {}
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=headers)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "http_error",
                "message": str(exc.detail),
                "details": None,
            },
        },
        headers=headers,
    )


@app.get("/health", tags=["Health"], summary="Public liveness")
async def health_check() -> dict:
    blueprint = get_host_blueprint()
    resp = blueprint.liveness()
    body = raise_for_host_response(resp)
    raw_status = str(body.get("status") or "healthy").strip().lower()
    status_out = "healthy" if raw_status in ("ok", "healthy", "ready") else raw_status
    return {
        "status": status_out,
        "service": settings.bfa_service_slug,
        "version": settings.service_version,
        "auth_test_mode": settings.auth_test_mode,
    }


@app.get("/health/ready", tags=["Health"], summary="Authenticated readiness detail")
async def readiness_check(
    request: Request,
    _: None = Depends(require_readiness_access),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    token = _resolve_bearer_token(request, credentials)
    blueprint = get_host_blueprint()
    resp = await blueprint.readiness(ManagementRequest(token=token or ""))
    body = raise_for_host_response(resp)
    return {
        "status": body.get("status", "ready"),
        "service": settings.bfa_service_slug,
        "version": settings.service_version,
        "dependencies": body.get("dependencies", []),
    }


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["HTTPBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "AyDEO API JWT (Entra / AUTH_TEST_MODE mock)",
    }
    for path, path_item in schema.get("paths", {}).items():
        if path.startswith("/api/v1/bfa") or path == "/health/ready":
            for method in path_item.values():
                if isinstance(method, dict):
                    method.setdefault("security", [{"HTTPBearer": []}])
        elif path == "/health":
            for method in path_item.values():
                if isinstance(method, dict):
                    method["security"] = []
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
