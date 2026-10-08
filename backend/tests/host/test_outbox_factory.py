"""Audit outbox factory tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from outbox import NullOutbox

from src.host import outbox_factory
from src.host.outbox_factory import build_host_outbox, close_audit_outbox_if_active
from src.host.runtime_de_outbox import RuntimeDeOutbox


@pytest.fixture(autouse=True)
def _reset_outbox_registry() -> None:
    outbox_factory.reset_audit_outbox_registry_for_tests()
    yield
    outbox_factory.reset_audit_outbox_registry_for_tests()


def _clear_audit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "AYDEO_AUDIT_URL",
        "AYDEO_AUDIT_SPOOL_PATH",
        "OUTBOX_INTERNAL_SERVICE_TOKEN",
        "AYDEO_INTERNAL_SERVICE_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_build_host_outbox_returns_null_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_audit_env(monkeypatch)
    outbox = build_host_outbox()
    assert isinstance(outbox, RuntimeDeOutbox)
    assert isinstance(outbox._inner, NullOutbox)


def test_build_host_outbox_whitespace_only_env_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_audit_env(monkeypatch)
    monkeypatch.setenv("AYDEO_AUDIT_URL", "   ")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", "  ")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", " ")
    outbox = build_host_outbox()
    assert isinstance(outbox, RuntimeDeOutbox)
    assert isinstance(outbox._inner, NullOutbox)


@pytest.mark.parametrize(
    ("env", "missing_fragment"),
    [
        ({"AYDEO_AUDIT_URL": "http://audit.local:8003"}, "AYDEO_AUDIT_SPOOL_PATH"),
        ({"OUTBOX_INTERNAL_SERVICE_TOKEN": "tok"}, "AYDEO_AUDIT_URL"),
        ({"AYDEO_AUDIT_SPOOL_PATH": "/tmp/spool"}, "AYDEO_AUDIT_URL"),
        (
            {
                "AYDEO_AUDIT_URL": "http://audit.local:8003",
                "OUTBOX_INTERNAL_SERVICE_TOKEN": "tok",
            },
            "AYDEO_AUDIT_SPOOL_PATH",
        ),
    ],
)
def test_build_host_outbox_partial_config_raises(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    missing_fragment: str,
) -> None:
    _clear_audit_env(monkeypatch)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="Partial audit configuration") as exc:
        build_host_outbox()
    assert missing_fragment in str(exc.value)


def test_build_host_outbox_partial_whitespace_url_with_real_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_audit_env(monkeypatch)
    monkeypatch.setenv("AYDEO_AUDIT_URL", "   ")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", "/tmp/spool")
    with pytest.raises(ValueError, match="Partial audit configuration") as exc:
        build_host_outbox()
    assert "AYDEO_AUDIT_URL" in str(exc.value)


@patch("src.host.outbox_factory.create_audit_outbox")
def test_build_host_outbox_all_set_wires_audit_outbox(
    mock_create: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _clear_audit_env(monkeypatch)
    audit_outbox = MagicMock(name="AuditOutbox")
    mock_create.return_value = audit_outbox
    monkeypatch.setenv("AYDEO_AUDIT_URL", "http://audit.local:8003")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", str(tmp_path / "spool"))

    outbox = build_host_outbox()
    assert isinstance(outbox, RuntimeDeOutbox)
    assert outbox._inner is audit_outbox
    mock_create.assert_called_once()


@patch("src.host.outbox_factory.create_audit_outbox")
def test_build_host_outbox_token_via_outbox_alias_only(
    mock_create: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _clear_audit_env(monkeypatch)
    audit_outbox = MagicMock(name="AuditOutbox")
    mock_create.return_value = audit_outbox
    monkeypatch.setenv("AYDEO_AUDIT_URL", "http://audit.local:8003")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "alias-token")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", str(tmp_path / "spool"))

    outbox = build_host_outbox()
    assert isinstance(outbox, RuntimeDeOutbox)
    assert outbox._inner is audit_outbox


@patch("src.host.outbox_factory.create_audit_outbox")
def test_build_host_outbox_sdk_config_error_wrapped(
    mock_create: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from aydeo_audit_sdk.errors import AuditSdkConfigError

    mock_create.side_effect = AuditSdkConfigError("AYDEO_AUDIT_SPOOL_PATH is required for audit outbox")
    _clear_audit_env(monkeypatch)
    monkeypatch.setenv("AYDEO_AUDIT_URL", "http://audit.local:8003")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", str(tmp_path / "spool"))
    with pytest.raises(ValueError, match="AYDEO_AUDIT_SPOOL_PATH"):
        build_host_outbox()


def test_close_audit_outbox_if_active_noop_when_never_wired() -> None:
    close_audit_outbox_if_active()


@patch("src.host.outbox_factory.create_audit_outbox")
def test_close_audit_outbox_if_active_closes_registered_outbox(
    mock_create: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from aydeo_audit_sdk.adapter.outbox import AuditOutbox

    audit_outbox = MagicMock(spec=AuditOutbox)
    mock_create.return_value = audit_outbox
    _clear_audit_env(monkeypatch)
    monkeypatch.setenv("AYDEO_AUDIT_URL", "http://audit.local:8003")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", str(tmp_path / "spool"))
    build_host_outbox()
    close_audit_outbox_if_active()
    audit_outbox.close.assert_called_once()
