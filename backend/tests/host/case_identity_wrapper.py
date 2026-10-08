"""Test-only case-authority overlay. Not a production facts source."""

from __future__ import annotations

from dataclasses import dataclass, replace

from bfa.aydeo_host.case_state import CaseStateFacts

from src.host.case_state_adapter import AydeoCaseStateAdapter


@dataclass(frozen=True)
class CaseIdentityOverlay:
    assignee_subject: str | None = None
    consulting_entitled: bool = False


class OverlayCaseStateAdapter:
    """Delegate to the real adapter, then replace identity fields for tests."""

    def __init__(
        self,
        overlay: CaseIdentityOverlay,
        inner: AydeoCaseStateAdapter | None = None,
    ) -> None:
        self._overlay = overlay
        self._inner = inner or AydeoCaseStateAdapter()

    async def resolve(
        self,
        *,
        case_id: str,
        thread_id: str | None = None,
        invoking_subject: str | None = None,
    ) -> CaseStateFacts:
        facts = await self._inner.resolve(
            case_id=case_id,
            thread_id=thread_id,
            invoking_subject=invoking_subject,
        )
        return replace(
            facts,
            assignee_subject=self._overlay.assignee_subject,
            consulting_entitled=self._overlay.consulting_entitled,
        )


def wrap_case_state_adapter(
    inner: AydeoCaseStateAdapter,
    overlay: CaseIdentityOverlay,
) -> OverlayCaseStateAdapter:
    return OverlayCaseStateAdapter(overlay, inner=inner)


__all__ = [
    "CaseIdentityOverlay",
    "OverlayCaseStateAdapter",
    "wrap_case_state_adapter",
]
