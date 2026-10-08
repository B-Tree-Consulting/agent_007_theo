"""Pass-through wrapper for the blueprint runtime identity validator.

Audit ``digital_employee_id`` is capability ``de_id``, set by
``CapabilityValidator`` — never Entra ``sub`` / ``oid``.
"""

from __future__ import annotations

from typing import Any


def wrap_runtime_identity_validator(inner: Any) -> Any:
    """Wrap blueprint runtime identity validator without capturing Entra subject."""

    class _RuntimeDeIdentityValidator:
        def validate_entra(self, token: str, *, correlation_id: str | None = None) -> Any:
            return inner.validate_entra(token, correlation_id=correlation_id)

    return _RuntimeDeIdentityValidator()
