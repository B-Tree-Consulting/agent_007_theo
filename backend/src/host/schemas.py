"""HTTP request/response models for BFA host routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BfaCatalogServiceInfo(BaseModel):
    slug: str
    version: str
    confirm_test_mode: bool = False
    invoke_diagnostic_mode: bool = False


class BfaCatalogResponse(BaseModel):
    operating_context: str
    service: BfaCatalogServiceInfo
    tools: list[dict[str, Any]]


class BfaDiagnosticServiceInfo(BaseModel):
    slug: str
    version: str


class BfaDiagnosticInvokePingResponse(BaseModel):
    status: str
    diagnostic: str
    service: BfaDiagnosticServiceInfo


class BfaInvokeRequest(BaseModel):
    tool_name: str
    tool_version: str = Field(..., description="BFA tool descriptor version")
    invoke_phase: str = Field(
        default="execute",
        description='Invoke phase: "execute" (default) or "confirm" for plan confirmation',
    )
    plan_token: str | None = Field(
        default=None,
        description="Frozen plan token for confirm phase (top-level; not nested under inputs)",
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Base tool input payload (flat on confirm phase; plan_token is separate)",
    )
    case_id: str | None = None
    thread_id: str | None = None
    correlation_id: str | None = None

    # Lane A (Chat grants)
    handoff_invoke_grant: str | None = Field(
        default=None,
        description="Chat-issued handoff invoke grant (Lane A). Required in production when confirm_test_mode is false.",
    )
    turn_invoke_grant: str | None = Field(
        default=None,
        description="Chat-issued turn invoke grant (Lane A). Optional/phase-specific per platform contract.",
    )

    # Lane B (superior approval)
    approval_record_id: str | None = Field(
        default=None,
        description="Superior approval record id (routing/correlation; not trust material).",
    )
    approval_execution_proof: str | None = Field(
        default=None,
        description="Platform-minted approval execution proof JWT (approval_proof_v1). Required in production for Lane B confirm.",
    )


class BfaInvokeResponse(BaseModel):
    status: str
    correlation_id: str
    trace: list[dict[str, Any]] = Field(default_factory=list)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
