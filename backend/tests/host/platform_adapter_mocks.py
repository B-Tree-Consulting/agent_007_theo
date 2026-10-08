"""Test-mode platform adapter bundle for AUTH_TEST_MODE HTTP and harness tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from bfa.aydeo_host import VerifiedInvokeContext

from src.host.adapters import CapabilityValidator, ManagementAuthorizer, RuntimeIdentityValidator
from src.host.runtime_de_identity import wrap_runtime_identity_validator


class _PermissiveGrantVerifier:
    async def verify_invoke(self, request, *, tool_name: str, grant_kind: str, grant: object) -> VerifiedInvokeContext:
        del request, tool_name, grant_kind, grant
        return VerifiedInvokeContext(attrs={})


def build_test_platform_adapters() -> MagicMock:
    adapters = MagicMock()
    adapters.management_authorizer = ManagementAuthorizer()
    adapters.runtime_identity_validator = wrap_runtime_identity_validator(RuntimeIdentityValidator())
    adapters.capability_validator = CapabilityValidator()
    adapters.invoke_grant_verifier = _PermissiveGrantVerifier()
    adapters.lane_b_confirm_verifier = object()
    return adapters
