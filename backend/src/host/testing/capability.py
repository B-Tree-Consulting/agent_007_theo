"""Mock BFA capability JWT mint/decode for AUTH_TEST_MODE."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from src.config import get_settings
from src.host.capability import CapabilityToolClaim, VerifiedCapability
from src.shared.bfa_capability_contract import CAPABILITY_ALGORITHM, CAPABILITY_AUD
from src.shared.test_utils import TEST_SECRET_KEY

DEFAULT_BFA_SERVICE_ID = "00000000-0000-4000-8000-000000000001"


def mint_mock_capability_token(
    de_id: str,
    tools: list[dict[str, str]],
    *,
    sub: str | None = None,
    include_de_id: bool = True,
    bfa_service_id: str | None = None,
    bfa_service_slug: str | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub if sub is not None else de_id,
        "iss": "aydeo-test",
        "aud": CAPABILITY_AUD,
        "iat": now,
        "exp": now + timedelta(hours=1),
        "bfa_service_id": bfa_service_id or DEFAULT_BFA_SERVICE_ID,
        "bfa_service_slug": bfa_service_slug or settings.bfa_service_slug,
        "tools": tools,
    }
    if include_de_id:
        payload["de_id"] = de_id
    return jwt.encode(payload, TEST_SECRET_KEY, algorithm="HS256")


def decode_mock_capability_token(token: str) -> VerifiedCapability:
    payload = jwt.decode(
        token,
        TEST_SECRET_KEY,
        algorithms=["HS256", CAPABILITY_ALGORITHM],
        options={"verify_aud": False, "verify_iss": False},
    )
    tools: list[CapabilityToolClaim] = []
    for entry in payload.get("tools") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("tool_name") or entry.get("name")
        # Defensive: skip malformed JWT claims with legacy .confirm suffix (not public catalog rows).
        if not name or str(name).endswith(".confirm"):
            continue
        version = str(entry.get("version") or "")
        if not version:
            continue
        risk = str(entry.get("risk") or "low")
        tools.append(CapabilityToolClaim(tool_name=str(name), version=version, risk=risk))
    raw_de_id = payload.get("de_id")
    de_id = str(raw_de_id).strip() if raw_de_id is not None else ""
    return VerifiedCapability(
        subject=str(payload.get("sub") or "").strip(),
        de_id=de_id,
        bfa_service_id=str(payload.get("bfa_service_id") or ""),
        bfa_service_slug=str(payload.get("bfa_service_slug") or ""),
        tools=tuple(tools),
    )


def catalog_tools_for_mock_capability(
    catalog: list[dict[str, Any]],
    *,
    code_tools: dict[str, Any] | None = None,
    default_risk: str = "low",
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    tools_by_name = code_tools or {}
    for entry in catalog:
        name = entry.get("name")
        if not name:
            continue
        td = tools_by_name.get(str(name))
        version = entry.get("version") or (getattr(td, "version", None) if td else None)
        if not version:
            continue
        risk = str(entry.get("risk") or getattr(td, "risk", None) or default_risk)
        out.append({"tool_name": str(name), "version": str(version), "risk": risk})
    return out
