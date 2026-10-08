"""Capability JWT claim types for the host sample."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityToolClaim:
    tool_name: str
    version: str
    risk: str


@dataclass(frozen=True)
class VerifiedCapability:
    subject: str
    de_id: str
    bfa_service_id: str
    bfa_service_slug: str
    tools: tuple[CapabilityToolClaim, ...]
