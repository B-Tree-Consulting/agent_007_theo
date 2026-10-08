"""Tests for runtime DE identity propagation into audit outbox events."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from aydeo_audit_sdk.adapter.mapping import outbox_event_to_envelope
from outbox import InMemoryOutbox
from outbox.models import OutboxEvent

from src.host.request_scope import (
    get_runtime_de_id,
    get_runtime_request_scope,
    set_runtime_de_id,
    set_runtime_request_context,
)
from src.host.runtime_de_identity import wrap_runtime_identity_validator
from src.config import get_settings
from src.host.runtime_de_outbox import RuntimeDeOutbox

_FACADE_SHELL_PLACEHOLDER_DE_ID = "00000000-0000-0000-0000-000000000000"


def test_runtime_de_outbox_overrides_shell_placeholder() -> None:
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    runtime_de = "11111111-1111-4111-8111-111111111111"
    event = OutboxEvent(
        digital_employee_id=_FACADE_SHELL_PLACEHOLDER_DE_ID,
        action_domain="example",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        with set_runtime_request_context():
            set_runtime_de_id(runtime_de)
            await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].digital_employee_id == runtime_de
    assert inner.events[0].action_domain == f"{get_settings().bfa_service_slug}.example"


def test_runtime_de_outbox_fills_missing_digital_employee_id() -> None:
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    runtime_de = "22222222-2222-4222-8222-222222222222"
    event = OutboxEvent(
        action_domain="example",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="actionkit",
        type="action.started",
    )

    async def _run() -> None:
        with set_runtime_request_context():
            set_runtime_de_id(runtime_de)
            await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].digital_employee_id == runtime_de
    assert inner.events[0].action_domain == f"{get_settings().bfa_service_slug}.example"


def test_runtime_de_outbox_omits_placeholder_without_capability_de_id() -> None:
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = OutboxEvent(
        digital_employee_id=_FACADE_SHELL_PLACEHOLDER_DE_ID,
        action_domain="example",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].digital_employee_id is None
    assert inner.events[0].action_domain == f"{get_settings().bfa_service_slug}.example"


def test_runtime_de_outbox_leaves_kit_stamped_de_id() -> None:
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    kit_de = "55555555-5555-4555-8555-555555555555"
    other_scope = "66666666-6666-4666-8666-666666666666"
    event = OutboxEvent(
        digital_employee_id=kit_de,
        action_domain="example",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        with set_runtime_request_context():
            set_runtime_de_id(other_scope)
            await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].digital_employee_id == kit_de


def test_runtime_de_outbox_maps_action_domain_to_slug_dot_kit_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("BFA_SERVICE_SLUG", "custom-bfa-slug")
    from src.config import get_settings

    get_settings.cache_clear()
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = OutboxEvent(
        action_domain="example",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        await outbox.append(event)

    try:
        asyncio.run(_run())
        assert inner.events[0].action_domain == "custom-bfa-slug.example"
    finally:
        get_settings.cache_clear()


def test_composite_audit_action_domain_avoids_double_prefix() -> None:
    from src.host.runtime_de_outbox import composite_audit_action_domain

    assert composite_audit_action_domain("agent-007-theo", "example") == "agent-007-theo.example"
    assert composite_audit_action_domain("agent-007-theo", "agent-007-theo.example") == "agent-007-theo.example"
    assert composite_audit_action_domain("", "example") == "example"


def test_runtime_de_identity_validator_does_not_set_entra_as_de_id() -> None:
    class _Inner:
        def validate_entra(self, token: str, *, correlation_id: str | None = None):
            del token, correlation_id
            return type("Identity", (), {"subject": "33333333-3333-4333-8333-333333333333"})()

    validator = wrap_runtime_identity_validator(_Inner())
    with set_runtime_request_context():
        assert get_runtime_de_id() is None
        identity = validator.validate_entra("token")
        assert identity.subject == "33333333-3333-4333-8333-333333333333"
        assert get_runtime_de_id() is None


class _RecordingOutbox:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def append(self, event: object) -> None:
        self.events.append(event)


def _kit_event(**overrides: object) -> OutboxEvent:
    payload: dict[str, object] = {
        "digital_employee_id": _FACADE_SHELL_PLACEHOLDER_DE_ID,
        "action_domain": "example",
        "action_name": "example_action",
        "action_version": "1.0.0",
        "action_execution_id": uuid4(),
        "source": "bfa",
        "type": "approval.requested",
    }
    payload.update(overrides)
    return OutboxEvent(**payload)  # type: ignore[arg-type]


def _mapped_envelope(event: object):
    envelope = outbox_event_to_envelope(event)
    assert envelope is not None
    return envelope


def test_runtime_de_outbox_fills_blank_correlation_id_from_invoke_body() -> None:
    inner = _RecordingOutbox()
    outbox = RuntimeDeOutbox(inner)
    runtime_de = "44444444-4444-4444-8444-444444444444"

    async def _run() -> None:
        with set_runtime_request_context(correlation_id="  cid-invoke-1  "):
            set_runtime_de_id(runtime_de)
            await outbox.append(_kit_event())

    asyncio.run(_run())
    stamped = inner.events[0]
    assert isinstance(stamped, OutboxEvent)
    assert stamped.correlation_id == "cid-invoke-1"
    assert stamped.type == "approval.requested"
    assert stamped.source == "bfa"
    assert stamped.action_name == "example_action"
    assert stamped.digital_employee_id == runtime_de
    assert stamped.action_domain == f"{get_settings().bfa_service_slug}.example"
    envelope = _mapped_envelope(stamped)
    assert envelope.correlation_id == "cid-invoke-1"
    assert envelope.invoke_phase is None
    assert envelope.tool_kind is None
    assert envelope.authorization_id is None
    assert envelope.authorization_source is None


def test_runtime_de_outbox_fills_whitespace_kit_correlation_id() -> None:
    inner = _RecordingOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = _kit_event(correlation_id="   ")

    async def _run() -> None:
        with set_runtime_request_context(correlation_id="body-c"):
            await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].correlation_id == "body-c"


@pytest.mark.parametrize("cid", ["", "  ", None, 123])
def test_runtime_de_outbox_blank_or_non_str_cid_leaves_correlation_null(cid: object) -> None:
    inner = _RecordingOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = _kit_event()

    async def _run() -> None:
        with set_runtime_request_context(correlation_id=cid):
            await outbox.append(event)

    asyncio.run(_run())
    appended = inner.events[0]
    assert isinstance(appended, OutboxEvent)
    assert appended.correlation_id is None
    assert appended.action_domain == f"{get_settings().bfa_service_slug}.example"


def test_runtime_de_outbox_unset_scope_leaves_correlation_null() -> None:
    inner = _RecordingOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = _kit_event()

    async def _run() -> None:
        await outbox.append(event)

    asyncio.run(_run())
    appended = inner.events[0]
    assert isinstance(appended, OutboxEvent)
    assert appended.correlation_id is None


@pytest.mark.parametrize("scope_cid", [None, "", "other-id"])
def test_runtime_de_outbox_keeps_kit_correlation_id(scope_cid: str | None) -> None:
    inner = _RecordingOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = _kit_event(correlation_id="C")

    async def _run() -> None:
        if scope_cid is None:
            await outbox.append(event)
            return
        with set_runtime_request_context(correlation_id=scope_cid):
            await outbox.append(event)

    asyncio.run(_run())
    assert inner.events[0].correlation_id == "C"


def test_runtime_de_outbox_passes_invoke_envelope_fields() -> None:
    inner = _RecordingOutbox()
    outbox = RuntimeDeOutbox(inner)
    authorization_id = uuid4()
    event = _kit_event(
        correlation_id="C",
        invoke_phase="confirm",
        tool_kind="setstate",
        authorization_id=authorization_id,
        authorization_source="handoff_grant",
    )

    async def _run() -> None:
        with set_runtime_request_context(correlation_id="other-id"):
            await outbox.append(event)

    asyncio.run(_run())
    appended = inner.events[0]
    assert appended.correlation_id == "C"
    assert appended.invoke_phase == "confirm"
    assert appended.tool_kind == "setstate"
    assert appended.authorization_id == authorization_id
    assert appended.authorization_source == "handoff_grant"
    assert appended.digital_employee_id is None
    assert appended.action_domain == f"{get_settings().bfa_service_slug}.example"
    envelope = _mapped_envelope(appended)
    assert envelope.correlation_id == "C"
    assert envelope.invoke_phase == "confirm"
    assert envelope.tool_kind == "setstate"
    assert envelope.authorization_id == authorization_id
    assert envelope.authorization_source == "handoff_grant"


def test_runtime_de_outbox_stamp_exception_appends_post_copy_event(monkeypatch: pytest.MonkeyPatch) -> None:
    inner = _RecordingOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = _kit_event()

    def _boom() -> None:
        raise RuntimeError("scope failed")

    monkeypatch.setattr("src.host.runtime_de_outbox.get_runtime_request_scope", _boom)

    async def _run() -> None:
        with set_runtime_request_context(correlation_id="cid-1"):
            await outbox.append(event)

    asyncio.run(_run())
    appended = inner.events[0]
    assert appended is not event
    assert isinstance(appended, OutboxEvent)
    assert appended.correlation_id is None
    assert appended.action_domain == f"{get_settings().bfa_service_slug}.example"


def test_nested_unset_does_not_clobber_outer_correlation_id() -> None:
    with set_runtime_request_context(correlation_id="cid-outer"):
        assert get_runtime_request_scope().correlation_id == "cid-outer"
        with set_runtime_request_context():
            assert get_runtime_request_scope().correlation_id == "cid-outer"
        assert get_runtime_request_scope().correlation_id == "cid-outer"


def test_runtime_de_outbox_flush_and_close_delegated() -> None:
    class _Inner:
        def __init__(self) -> None:
            self.flushed = False
            self.closed = False

        async def flush(self) -> None:
            self.flushed = True

        def close(self) -> None:
            self.closed = True

    inner = _Inner()
    outbox = RuntimeDeOutbox(inner)

    async def _run() -> None:
        await outbox.flush()

    asyncio.run(_run())
    outbox.close()
    assert inner.flushed is True
    assert inner.closed is True


def test_runtime_de_outbox_close_noops_without_inner_close() -> None:
    RuntimeDeOutbox(object()).close()


def test_composite_audit_action_domain_empty_kit_domain() -> None:
    from src.host.runtime_de_outbox import composite_audit_action_domain

    assert composite_audit_action_domain("agent-007-theo", "") == "agent-007-theo"
    assert composite_audit_action_domain("", "") == ""


def test_runtime_de_outbox_no_updates_when_kit_stamp_and_empty_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("BFA_SERVICE_SLUG", "")
    from src.config import get_settings

    get_settings.cache_clear()
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    kit_de = "77777777-7777-4777-8777-777777777777"
    event = OutboxEvent(
        digital_employee_id=kit_de,
        action_domain="",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        await outbox.append(event)

    try:
        asyncio.run(_run())
        assert inner.events[0] is event
        assert inner.events[0].digital_employee_id == kit_de
        assert inner.events[0].action_domain == ""
    finally:
        get_settings.cache_clear()


def test_runtime_de_outbox_keeps_kit_correlation_without_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("BFA_SERVICE_SLUG", "")
    from src.config import get_settings

    get_settings.cache_clear()
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    kit_de = "88888888-8888-4888-8888-888888888888"
    event = OutboxEvent(
        digital_employee_id=kit_de,
        action_domain="",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
        correlation_id="C",
    )

    async def _run() -> None:
        with set_runtime_request_context(correlation_id="other-id"):
            await outbox.append(event)

    try:
        asyncio.run(_run())
        assert inner.events[0] is event
        assert inner.events[0].correlation_id == "C"
    finally:
        get_settings.cache_clear()


def test_runtime_de_outbox_omits_placeholder_without_action_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("BFA_SERVICE_SLUG", "")
    from src.config import get_settings

    get_settings.cache_clear()
    inner = InMemoryOutbox()
    outbox = RuntimeDeOutbox(inner)
    event = OutboxEvent(
        digital_employee_id=_FACADE_SHELL_PLACEHOLDER_DE_ID,
        action_domain="",
        action_name="example_action",
        action_version="1.0.0",
        action_execution_id=uuid4(),
        source="bfa",
        type="approval.requested",
    )

    async def _run() -> None:
        await outbox.append(event)

    try:
        asyncio.run(_run())
        assert inner.events[0].digital_employee_id is None
        assert inner.events[0].action_domain == ""
    finally:
        get_settings.cache_clear()
