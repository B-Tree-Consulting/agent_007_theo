"""Wire BFA kit Outbox: NullOutbox or AyDEO Audit SDK AuditOutbox."""

from __future__ import annotations

from typing import Any

from aydeo_audit_sdk import AuditSdkSettings, create_audit_outbox
from aydeo_audit_sdk.adapter.outbox import AuditOutbox
from aydeo_audit_sdk.errors import AuditSdkConfigError
from outbox import NullOutbox

from src.host.runtime_de_outbox import RuntimeDeOutbox

_active_audit_outbox: AuditOutbox | None = None


def _is_set(value: str | None) -> bool:
    return bool((value or "").strip())


def _audit_env_snapshot() -> tuple[bool, bool, bool]:
    sdk = AuditSdkSettings()
    return (
        _is_set(sdk.audit_url),
        _is_set(sdk.resolved_internal_service_token),
        _is_set(sdk.spool_path),
    )


def _raise_partial_config(*, url_set: bool, token_set: bool, spool_set: bool) -> None:
    missing: list[str] = []
    if not url_set:
        missing.append("AYDEO_AUDIT_URL")
    if not token_set:
        missing.append("OUTBOX_INTERNAL_SERVICE_TOKEN or AYDEO_INTERNAL_SERVICE_TOKEN")
    if not spool_set:
        missing.append("AYDEO_AUDIT_SPOOL_PATH")
    joined = ", ".join(missing)
    raise ValueError(f"Partial audit configuration: {joined} required when audit integration is enabled")


def build_host_outbox() -> Any:
    """Return NullOutbox or a production AuditOutbox based on environment."""
    global _active_audit_outbox

    url_set, token_set, spool_set = _audit_env_snapshot()

    if not url_set and not token_set and not spool_set:
        return RuntimeDeOutbox(NullOutbox())

    if not (url_set and token_set and spool_set):
        _raise_partial_config(url_set=url_set, token_set=token_set, spool_set=spool_set)

    sdk_settings = AuditSdkSettings()
    try:
        outbox = create_audit_outbox(sdk_settings)
    except AuditSdkConfigError as exc:
        raise ValueError(str(exc)) from exc

    _active_audit_outbox = outbox
    return RuntimeDeOutbox(outbox)


def close_audit_outbox_if_active() -> None:
    """Stop FlushWorker when an AuditOutbox was constructed; no-op otherwise."""
    global _active_audit_outbox
    if _active_audit_outbox is not None:
        _active_audit_outbox.close()
        _active_audit_outbox = None


def reset_audit_outbox_registry_for_tests() -> None:
    """Clear module registry between tests."""
    global _active_audit_outbox
    _active_audit_outbox = None
