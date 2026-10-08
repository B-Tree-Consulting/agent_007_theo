"""Capability JWT binding checks for AUTH_TEST_MODE."""

from __future__ import annotations

from fastapi import HTTPException, status

from src.host.capability import VerifiedCapability


async def bind_capability_to_de(
    verified: VerifiedCapability,
    *,
    entra_token: str,
    entra_subject: str,
) -> None:
    """Test-mode binding: capability JWT ``sub`` must match validated Entra subject."""
    del entra_token
    if (verified.subject or "").strip() != (entra_subject or "").strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BFA capability token is not bound to the authenticated DE identity",
        )
