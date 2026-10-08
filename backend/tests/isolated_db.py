"""Pytest-only Postgres database selection (never touch the dev application DB)."""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

_PYTEST_DB_SUFFIX = "_pytest"
_COMPOSE_POSTGRES_NETLOC_MARKER = "@postgres:5432/"
_HOST_PUBLISHED_POSTGRES_NETLOC = "@localhost:5437/"


def pytest_database_name_from_base(base_db: str) -> str:
    if base_db.endswith(_PYTEST_DB_SUFFIX):
        return base_db
    return f"{base_db}{_PYTEST_DB_SUFFIX}"


def is_pytest_database_name(db_name: str) -> bool:
    return db_name.endswith(_PYTEST_DB_SUFFIX)


def rewrite_compose_postgres_host_for_local_pytest(url: str) -> str:
    """Map docker-compose hostname to the published host port; keep path unchanged."""
    return url.replace(_COMPOSE_POSTGRES_NETLOC_MARKER, _HOST_PUBLISHED_POSTGRES_NETLOC)


def database_url_with_name(url: str, db_name: str) -> str:
    u = url.replace("postgresql+psycopg://", "postgresql://")
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc, f"/{db_name}", "", p.query, p.fragment))


def database_name_from_url(url: str) -> str:
    u = url.replace("postgresql+psycopg://", "postgresql://")
    path = (urlparse(u).path or "").strip("/")
    current_db = path.split("/")[0] if path else ""
    return current_db or "postgres"


def isolated_pytest_database_url(url: str) -> str:
    """Host/port from ``url``, database name forced to ``{base}_pytest``."""
    normalized = url.replace("postgresql+psycopg://", "postgresql://")
    return database_url_with_name(normalized, pytest_database_name_from_base(database_name_from_url(normalized)))


def maintenance_database_url(url: str, maintenance_db: str = "postgres") -> str:
    return database_url_with_name(url, maintenance_db)


def ensure_pytest_database_url() -> None:
    explicit = os.environ.get("PYTEST_DATABASE_URL", "").strip()
    raw = explicit or os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return

    normalized = raw.replace("postgresql+psycopg://", "postgresql://")
    current_db = database_name_from_url(normalized)

    if is_pytest_database_name(current_db):
        os.environ["DATABASE_URL"] = database_url_with_name(normalized, current_db)
        return

    test_db = pytest_database_name_from_base(current_db)
    isolated = isolated_pytest_database_url(normalized)
    admin_url = maintenance_database_url(normalized, "postgres")
    if current_db == "postgres":
        admin_url = maintenance_database_url(normalized, "template1")

    import psycopg
    from psycopg import sql

    conn = psycopg.connect(admin_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (test_db,),
            )
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))
    finally:
        conn.close()

    os.environ["DATABASE_URL"] = isolated
