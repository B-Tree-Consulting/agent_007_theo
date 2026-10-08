"""Outbox wrapper that stamps host audit identity onto kit outbox events."""

from __future__ import annotations

from typing import Any

from outbox.models import OutboxEvent

from src.config import get_settings
from src.host.request_scope import get_runtime_de_id, get_runtime_request_scope

# Must match facade._FACADE_SHELL_PLACEHOLDER_DE_ID (kit shell identity in prod auth mode).
_FACADE_SHELL_PLACEHOLDER_DE_ID = "00000000-0000-0000-0000-000000000000"


def _invoke_correlation_blank(value: str | None) -> bool:
    """True when the kit left ``correlation_id`` unset or whitespace-only."""
    return not (value or "").strip()


def _invoke_body_correlation_id(value: object) -> str | None:
    """Return a stripped invoke-body correlation id, or None when it must not be stamped."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def composite_audit_action_domain(service_slug: str, kit_action_domain: str) -> str:
    """Build audit ``action_domain`` as ``{BFA_SERVICE_SLUG}.{kit domain}``."""
    slug = (service_slug or "").strip()
    domain = (kit_action_domain or "").strip()
    if not slug:
        return domain
    if not domain:
        return slug
    prefix = f"{slug}."
    if domain == slug or domain.startswith(prefix):
        return domain
    return f"{slug}.{domain}"


class RuntimeDeOutbox:
    """Stamp capability de_id, BFA service slug, and a blank invoke correlation_id onto outbox events."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def append(self, event: OutboxEvent) -> None:
        updates: dict[str, str | None] = {}
        runtime_de_id = get_runtime_de_id()
        current = (event.digital_employee_id or "").strip()
        if not current or current == _FACADE_SHELL_PLACEHOLDER_DE_ID:
            updates["digital_employee_id"] = runtime_de_id
        service_slug = (get_settings().bfa_service_slug or "").strip()
        audit_domain = composite_audit_action_domain(service_slug, event.action_domain)
        if audit_domain:
            updates["action_domain"] = audit_domain
        try:
            if _invoke_correlation_blank(event.correlation_id):
                cid = _invoke_body_correlation_id(get_runtime_request_scope().correlation_id)
                if cid is not None:
                    updates["correlation_id"] = cid
        except Exception:  # noqa: BLE001 - stamp must not block kit append
            pass
        if updates:
            event = event.model_copy(update=updates)
        await self._inner.append(event)

    async def flush(self) -> None:
        await self._inner.flush()

    def close(self) -> None:
        closer = getattr(self._inner, "close", None)
        if callable(closer):
            closer()
