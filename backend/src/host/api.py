"""BFA catalog / invoke HTTP routes."""

from __future__ import annotations

import logging
from typing import Any

from bfa.aydeo_host import HostErrorCode, ManagementRequest, RuntimeCatalogRequest, RuntimeInvokeRequest
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials

from src.config import get_settings
from src.host.auth import (
    BfaCatalogAccess,
    BfaRuntimeAccess,
    require_catalog_bearer,
    require_runtime_bearer,
    security,
)
from src.host.facade import get_host_bfa
from src.host.factory import get_host_blueprint
from src.host.http import raise_for_host_response
from src.host.request_scope import set_runtime_request_context
from src.host.schemas import (
    BfaCatalogResponse,
    BfaDiagnosticInvokePingResponse,
    BfaInvokeRequest,
    BfaInvokeResponse,
)
from src.shared.bfa_capability_contract import CAPABILITY_HEADER, normalize_capability_header_value
from src.shared.invoke_scope import bind_invoke_case_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bfa", tags=["BFA"])


async def _require_invoke_access(
    request: Request,
    body: BfaInvokeRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> BfaRuntimeAccess:
    del body
    return await require_runtime_bearer(request, credentials)


async def _require_diagnostic_invoke_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> BfaRuntimeAccess:
    if not get_settings().invoke_diagnostic_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return await require_runtime_bearer(request, credentials)


def _capability_token_from_request(request: Request) -> str | None:
    return normalize_capability_header_value(request.headers.get(CAPABILITY_HEADER))


def _serialize_execute_result(result: Any) -> BfaInvokeResponse:
    trace: list[dict[str, Any]] = []
    for step in result.trace or []:
        if hasattr(step, "model_dump"):
            trace.append(step.model_dump(mode="json"))
        elif isinstance(step, dict):
            trace.append(step)

    assertions: list[dict[str, Any]] = []
    for assertion in result.assertions or []:
        if hasattr(assertion, "model_dump"):
            assertions.append(assertion.model_dump(mode="json"))
        elif isinstance(assertion, dict):
            assertions.append(assertion)

    raw_outputs = result.outputs
    if isinstance(raw_outputs, dict):
        outputs = raw_outputs
    elif hasattr(raw_outputs, "model_dump"):
        outputs = raw_outputs.model_dump(mode="json")
    else:
        outputs = {}
    return BfaInvokeResponse(
        status=result.status,
        correlation_id=result.correlation_id,
        trace=trace,
        assertions=assertions,
        outputs=outputs,
    )


@router.get(
    "/catalog",
    response_model=BfaCatalogResponse,
    summary="List BFA tools available to the caller",
)
async def bfa_catalog(
    request: Request,
    access: BfaCatalogAccess = Depends(require_catalog_bearer),
    x_bfa_capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> BfaCatalogResponse:
    del x_bfa_capability
    blueprint = get_host_blueprint()
    cap_token = _capability_token_from_request(request)
    with set_runtime_request_context(entra_token=access.token):
        # Production: Blueprint/kit determines whether the token is management or runtime.
        # Try management first; if forbidden/unauthorized, fall back to runtime catalog.
        resp = await blueprint.management_catalog(ManagementRequest(token=access.token))
        if not resp.ok:
            mgmt_err = resp.error
            if mgmt_err and mgmt_err.code == HostErrorCode.UNAUTHENTICATED:
                raise_for_host_response(resp)
            resp = await blueprint.runtime_catalog(
                RuntimeCatalogRequest(
                    entra_token=access.token,
                    capability_token=cap_token,
                )
            )
    body = raise_for_host_response(resp)
    return BfaCatalogResponse(**body)


@router.post(
    "/diagnostics/invoke-ping",
    response_model=BfaDiagnosticInvokePingResponse,
    summary="Invoke-plane diagnostic (test mode only)",
)
async def bfa_diagnostic_invoke_ping(
    request: Request,
    access: BfaRuntimeAccess = Depends(_require_diagnostic_invoke_access),
    x_bfa_capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> BfaDiagnosticInvokePingResponse:
    del x_bfa_capability
    cap_token = _capability_token_from_request(request)
    blueprint = get_host_blueprint()
    with set_runtime_request_context(entra_token=access.token):
        resp = await blueprint.diagnostic_invoke_ping(
            RuntimeCatalogRequest(
                entra_token=access.token,
                capability_token=cap_token,
            )
        )
    body = raise_for_host_response(resp)
    return BfaDiagnosticInvokePingResponse(**body)


@router.post(
    "/invoke",
    response_model=BfaInvokeResponse,
    summary="Invoke a BFA tool",
)
async def bfa_invoke(
    request: Request,
    body: BfaInvokeRequest,
    access: BfaRuntimeAccess = Depends(_require_invoke_access),
    x_bfa_capability: str | None = Header(default=None, alias=CAPABILITY_HEADER),
) -> BfaInvokeResponse:
    del x_bfa_capability
    blueprint = get_host_blueprint()
    if body.tool_name not in get_host_bfa().tools():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown tool: {body.tool_name}",
        )
    cap_token = _capability_token_from_request(request)
    runtime_request = RuntimeInvokeRequest(
        tool_name=body.tool_name,
        tool_version=body.tool_version,
        invoke_phase=body.invoke_phase,
        plan_token=body.plan_token,
        inputs=body.inputs,
        capability_token=cap_token,
        entra_token=access.token,
        correlation_id=body.correlation_id,
        case_id=body.case_id,
        thread_id=body.thread_id,
        handoff_invoke_grant=body.handoff_invoke_grant,
        turn_invoke_grant=body.turn_invoke_grant,
        approval_record_id=body.approval_record_id,
        approval_execution_proof=body.approval_execution_proof,
    )
    with set_runtime_request_context(
        entra_token=access.token,
        correlation_id=body.correlation_id,
    ), bind_invoke_case_id(body.case_id, body.correlation_id, body.approval_record_id):
        resp = await blueprint.invoke(runtime_request)
    if resp.ok:
        return _serialize_execute_result(resp.body)
    if resp.error is not None:
        logger.warning(
            "bfa invoke denied tool=%s phase=%s case_id=%s code=%s status=%s message=%s details=%s",
            body.tool_name,
            body.invoke_phase,
            body.case_id,
            resp.error.code,
            resp.error.status_code,
            resp.error.message,
            resp.error.details,
        )
    raise_for_host_response(resp, tool_name=body.tool_name)
    raise AssertionError("unreachable")
