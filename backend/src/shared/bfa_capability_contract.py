"""Shared BFA capability-token contract constants."""

from __future__ import annotations

CAPABILITY_HEADER = "X-AyDEO-Capability-Token"
CAPABILITY_AUD = "aydeo-bfa"
CAPABILITY_ALGORITHM = "RS256"


def normalize_capability_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw or None
