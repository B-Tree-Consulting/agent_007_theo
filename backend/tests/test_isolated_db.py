"""Isolation of pytest Postgres from the live demo database."""

from __future__ import annotations

from tests.isolated_db import (
    database_name_from_url,
    isolated_pytest_database_url,
    is_pytest_database_name,
    pytest_database_name_from_base,
    rewrite_compose_postgres_host_for_local_pytest,
)

_COMPOSE_APP_URL = (
    "postgresql://agent-007-theo:secret@postgres:5432/agent-007-theo"
)


def test_compose_host_rewrite_keeps_application_database_name() -> None:
    rewritten = rewrite_compose_postgres_host_for_local_pytest(_COMPOSE_APP_URL)
    assert rewritten == (
        "postgresql://agent-007-theo:secret@localhost:5437/agent-007-theo"
    )
    assert database_name_from_url(rewritten) == "agent-007-theo"


def test_isolated_url_from_compose_app_url_uses_pytest_database() -> None:
    rewritten = rewrite_compose_postgres_host_for_local_pytest(_COMPOSE_APP_URL)
    isolated = isolated_pytest_database_url(rewritten)
    assert database_name_from_url(isolated) == "agent-007-theo_pytest"
    assert isolated.endswith("/agent-007-theo_pytest")
    assert "localhost:5437" in isolated


def test_explicit_pytest_url_without_suffix_is_still_isolated() -> None:
    """Host pytest used to assign PYTEST_DATABASE_URL to the live demo DB name."""
    live = "postgresql://u:p@localhost:5437/agent-007-theo"
    assert isolated_pytest_database_url(live) == (
        "postgresql://u:p@localhost:5437/agent-007-theo_pytest"
    )


def test_already_isolated_name_is_unchanged() -> None:
    url = "postgresql://u:p@localhost:5437/agent-007-theo_pytest"
    assert isolated_pytest_database_url(url) == url
    assert is_pytest_database_name(database_name_from_url(url))


def test_pytest_database_name_from_base() -> None:
    assert pytest_database_name_from_base("agent-007-theo") == "agent-007-theo_pytest"
    assert pytest_database_name_from_base("agent-007-theo_pytest") == "agent-007-theo_pytest"


def test_ensure_isolates_explicit_live_pytest_database_url(monkeypatch) -> None:
    """Regression: PYTEST_DATABASE_URL used to be applied as-is to the live demo DB."""
    import os

    import psycopg

    from tests.isolated_db import ensure_pytest_database_url

    live = "postgresql://u:p@localhost:5437/agent-007-theo"
    monkeypatch.setenv("PYTEST_DATABASE_URL", live)
    monkeypatch.setenv("DATABASE_URL", live)

    class _Cur:
        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return (1,)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            return None

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: _Conn())
    ensure_pytest_database_url()
    assert os.environ["DATABASE_URL"].endswith("/agent-007-theo_pytest")
    assert "agent-007-theo_pytest" in os.environ["DATABASE_URL"]
    assert os.environ["DATABASE_URL"].rstrip("/").split("/")[-1] != "agent-007-theo"
