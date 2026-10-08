"""FastAPI lifespan tests for audit outbox shutdown."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src import main as main_module
from src.host import outbox_factory
from src.host.outbox_factory import close_audit_outbox_if_active


@pytest.fixture(autouse=True)
def _reset_outbox_registry() -> None:
    outbox_factory.reset_audit_outbox_registry_for_tests()
    yield
    outbox_factory.reset_audit_outbox_registry_for_tests()


async def _run_lifespan_shutdown() -> None:
    async with main_module._app_lifespan(main_module.app):
        pass


def test_lifespan_shutdown_noop_without_audit_outbox() -> None:
    asyncio.run(_run_lifespan_shutdown())
    close_audit_outbox_if_active()


@patch("src.host.outbox_factory.create_audit_outbox")
def test_lifespan_shutdown_closes_registered_audit_outbox(
    mock_create: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from aydeo_audit_sdk.adapter.outbox import AuditOutbox

    audit_outbox = MagicMock(spec=AuditOutbox)
    mock_create.return_value = audit_outbox
    for key in (
        "AYDEO_AUDIT_URL",
        "AYDEO_AUDIT_SPOOL_PATH",
        "OUTBOX_INTERNAL_SERVICE_TOKEN",
        "AYDEO_INTERNAL_SERVICE_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AYDEO_AUDIT_URL", "http://audit.local:8003")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("AYDEO_AUDIT_SPOOL_PATH", str(tmp_path / "spool"))

    from src.config import get_settings
    from src.host.facade import get_host_bfa

    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    try:
        get_host_bfa()
        asyncio.run(_run_lifespan_shutdown())
        audit_outbox.close.assert_called_once()
    finally:
        get_host_bfa.cache_clear()
        get_settings.cache_clear()


def test_lifespan_shutdown_noop_when_facade_never_constructed() -> None:
    asyncio.run(_run_lifespan_shutdown())


@pytest.mark.no_host_canaries
def test_lifespan_startup_warms_host_tools_before_serving() -> None:
    """Docker/uvicorn must register tools at startup, not on first client request."""
    from src.host.facade import get_host_bfa
    from src.host.factory import get_host_blueprint
    from tests.host.canary_host_tools import sample_domain_bootstrap_present

    get_host_bfa.cache_clear()
    get_host_blueprint.cache_clear()
    try:
        if sample_domain_bootstrap_present():
            asyncio.run(_run_lifespan_shutdown())
            assert get_host_bfa().tools()
        else:
            with pytest.raises(RuntimeError, match="tools"):
                asyncio.run(_run_lifespan_shutdown())
    finally:
        get_host_bfa.cache_clear()
        get_host_blueprint.cache_clear()
