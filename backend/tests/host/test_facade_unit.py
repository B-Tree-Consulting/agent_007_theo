"""Host BFA facade shell tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from outbox import NullOutbox

from src.config import get_settings
from src.host import outbox_factory
from src.host.facade import _FACADE_SHELL_PLACEHOLDER_DE_ID, get_host_bfa
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


def test_facade_uses_test_de_id_in_auth_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("AUTH_TEST_MODE", "true")
    monkeypatch.setenv("BFA_TEST_DE_ID", "00000000-0000-4000-8000-0000000000ab")
    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    try:
        assert get_host_bfa()._employee_id == "00000000-0000-4000-8000-0000000000ab"
    finally:
        get_host_bfa.cache_clear()
        get_settings.cache_clear()


def test_facade_uses_placeholder_when_not_auth_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("AUTH_TEST_MODE", "false")
    monkeypatch.setenv("BFA_TEST_DE_ID", "00000000-0000-4000-8000-0000000000ab")
    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    try:
        assert get_host_bfa()._employee_id == _FACADE_SHELL_PLACEHOLDER_DE_ID
    finally:
        get_host_bfa.cache_clear()
        get_settings.cache_clear()


def test_facade_wires_null_outbox_when_audit_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    _clear_audit_env(monkeypatch)
    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    try:
        assert isinstance(get_host_bfa()._outbox, RuntimeDeOutbox)
        assert isinstance(get_host_bfa()._outbox._inner, NullOutbox)
    finally:
        get_host_bfa.cache_clear()
        get_settings.cache_clear()


@patch("src.host.outbox_factory.create_audit_outbox")
def test_facade_wires_audit_outbox_when_configured(
    mock_create,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    audit_outbox = mock_create.return_value
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    _clear_audit_env(monkeypatch)
    monkeypatch.setenv("AYDEO_AUDIT_URL", "http://audit.local:8003")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", str(tmp_path / "spool"))
    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    try:
        outbox = get_host_bfa()._outbox
        assert isinstance(outbox, RuntimeDeOutbox)
        assert outbox._inner is audit_outbox
    finally:
        get_host_bfa.cache_clear()
        get_settings.cache_clear()
