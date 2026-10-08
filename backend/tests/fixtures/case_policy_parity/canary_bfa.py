"""Dedicated BFA shell for case/hold parity canary (sample#23)."""

from __future__ import annotations

from typing import Any, ClassVar

from bfa import BFA, CallContext, Resolver

from tests.fixtures.case_policy_parity import canary_tools


class _CanaryResolver(Resolver):
    def get(self, key: str):
        return None

    def scoped(self, ctx: CallContext):
        class _Scoped:
            def get(self, key: str):
                return None

        return _Scoped()


class CanaryBFA(BFA):
    """Non-production BFA used only by the case/hold parity harness."""

    _cls_specs: ClassVar[list[dict[str, Any]]] = []


canary_tools.register(CanaryBFA)


def fresh_canary_bfa() -> CanaryBFA:
    """Return a new BFA instance; tools are bound to the class at module import."""
    return CanaryBFA(
        resolver=_CanaryResolver(),
        token_introspector=object(),  # type: ignore[arg-type]
        employee_id="canary-bfa",
    )
