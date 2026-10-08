"""Scenario-driven case facts adapter for parity harness only (non-production)."""

from __future__ import annotations

from bfa.aydeo_host import CaseStateFacts
from bfa.aydeo_host.case_state import CaseStateAdapter

_HARNESS_ASSIGNEE_SUBJECT = "de-123"
_HARNESS_IN_PROGRESS = "in_progress"


class ScenarioCaseStateAdapter:
    """Harness-only adapter for frozen parity vectors; not production case truth."""

    def __init__(
        self,
        *,
        case_state: str = "none",
        cms_mode: str = "normal",
    ) -> None:
        self._case_state = case_state
        self._cms_mode = cms_mode
        self.resolve_calls = 0

    async def resolve(
        self,
        *,
        case_id: str,
        thread_id: str | None = None,
        invoking_subject: str | None = None,
    ) -> CaseStateFacts:
        del case_id, thread_id, invoking_subject
        self.resolve_calls += 1
        if self._cms_mode == "hold_fail":
            return CaseStateFacts(
                exists=True,
                is_open=True,
                is_held=None,
                dependency_failure="hold_unavailable",
                assignee_subject=_HARNESS_ASSIGNEE_SUBJECT,
                status=_HARNESS_IN_PROGRESS,
            )
        if self._cms_mode == "scope_fail":
            return CaseStateFacts(
                exists=None,
                is_open=None,
                is_held=None,
                dependency_failure="scope_unavailable",
            )
        if self._case_state == "unknown":
            return CaseStateFacts(exists=False, is_open=None, is_held=None)
        if self._case_state == "closed":
            return CaseStateFacts(exists=True, is_open=False, is_held=False)
        if self._case_state == "held":
            return CaseStateFacts(
                exists=True,
                is_open=True,
                is_held=True,
                assignee_subject=_HARNESS_ASSIGNEE_SUBJECT,
                status=_HARNESS_IN_PROGRESS,
            )
        if self._case_state == "open":
            return CaseStateFacts(
                exists=True,
                is_open=True,
                is_held=False,
                assignee_subject=_HARNESS_ASSIGNEE_SUBJECT,
                status=_HARNESS_IN_PROGRESS,
            )
        return CaseStateFacts(exists=False, is_open=None, is_held=None)


def adapter_from_vector_setup(setup: dict[str, object]) -> ScenarioCaseStateAdapter:
    return ScenarioCaseStateAdapter(
        case_state=str(setup.get("case_state", "none")),
        cms_mode=str(setup.get("cms_mode", "normal")),
    )


__all__ = ["ScenarioCaseStateAdapter", "CaseStateAdapter", "adapter_from_vector_setup"]
