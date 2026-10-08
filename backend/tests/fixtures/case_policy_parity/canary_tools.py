"""Minimal low-risk canary fixture actions for frozen parity vectors."""

from __future__ import annotations

from typing import Any

from bfa import ExecuteContext
from pydantic import BaseModel

from tests.fixtures.case_policy_parity.mutation_tracker import mark_mutated

CANARY_ACTION_DIRECT = "canary_action_direct"
CANARY_ACTION_REFERENCE = "canary_action_reference"
CANARY_ACTION_MEDIUM = "canary_action_medium"
CANARY_QUERY_BOUNDED = "canary_query_bounded"
CANARY_FIXTURE_VERSION = "1.0.0"


class _ActionDirectInputs(BaseModel):
    attention_summary: str = "parity"


class _ActionReferenceInputs(BaseModel):
    body: str = "parity"


class _ActionMediumInputs(BaseModel):
    attention_summary: str = "parity"


class _QueryInputs(BaseModel):
    pass


class _QueryOutput(BaseModel):
    status: str = "ok"


def register(host_cls: type) -> None:
    @host_cls.setstate(
        name=CANARY_ACTION_DIRECT,
        describe="canary low-risk direct action fixture",
        input_model=_ActionDirectInputs,
        risk="low",
        version=CANARY_FIXTURE_VERSION,
        systems=("CMS",),
        case_tool_class="case_effect",
    )
    async def canary_action_direct(self: Any, inputs: _ActionDirectInputs) -> dict[str, str]:
        del self, inputs
        mark_mutated()
        return {"status": "ok"}

    @host_cls.setstate(
        name=CANARY_ACTION_REFERENCE,
        describe="canary low-risk reference action fixture",
        input_model=_ActionReferenceInputs,
        risk="low",
        version=CANARY_FIXTURE_VERSION,
        systems=("CMS",),
        case_tool_class="case_effect",
    )
    async def canary_action_reference(self: Any, inputs: _ActionReferenceInputs) -> dict[str, str]:
        del self, inputs
        mark_mutated()
        return {"status": "ok"}

    @host_cls.setstate(
        name=CANARY_ACTION_MEDIUM,
        describe="canary medium-risk action fixture",
        input_model=_ActionMediumInputs,
        risk="medium",
        version=CANARY_FIXTURE_VERSION,
        systems=("CMS",),
        case_tool_class="case_effect",
    )
    async def canary_action_medium(self: Any, inputs: _ActionMediumInputs) -> dict[str, str]:
        del self, inputs
        mark_mutated()
        return {"status": "ok"}

    @host_cls.query(
        name=CANARY_QUERY_BOUNDED,
        describe="canary low-risk bounded query fixture",
        version=CANARY_FIXTURE_VERSION,
        risk="low",
        execute_context=ExecuteContext.DE_AUTONOMOUS,
        case_tool_class="read",
        input_model=_QueryInputs,
        output_model=_QueryOutput,
    )
    async def canary_query_bounded(self: Any, inputs: _QueryInputs) -> _QueryOutput:
        del self, inputs
        return _QueryOutput(status="ok")

    setattr(host_cls, canary_action_direct.__name__, canary_action_direct)
    setattr(host_cls, canary_action_reference.__name__, canary_action_reference)
    setattr(host_cls, canary_action_medium.__name__, canary_action_medium)
    setattr(host_cls, canary_query_bounded.__name__, canary_query_bounded)
