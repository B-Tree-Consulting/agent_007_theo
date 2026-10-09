"""Shared pytest fixtures (optional Postgres + Alembic)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

if os.environ.get("PYTEST_XDIST_WORKER"):
    pytest.exit(
        "pytest-xdist is not supported for this suite (use single-worker pytest).",
        returncode=2,
    )

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _REPO_ROOT / ".env"
if load_dotenv and _ENV_PATH.exists():
    # Ensure local pytest defaults match docker-compose env where possible.
    # Do not override explicitly-set environment variables.
    load_dotenv(_ENV_PATH, override=False)

# BEGIN_DEFAULT_DATABASE_URL
os.environ.setdefault("POSTGRES_USER", "agent-007-theo")
os.environ.setdefault("POSTGRES_PASSWORD", "changeme-generate-strong-password")
os.environ.setdefault("POSTGRES_DB", "agent-007-theo")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5437")

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://{user}:{pw}@{host}:{port}/{db}".format(
        user=os.environ["POSTGRES_USER"],
        pw=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        db=os.environ["POSTGRES_DB"],
    ),
)
# END_DEFAULT_DATABASE_URL


def _database_url_configured() -> bool:
    return bool((os.environ.get("DATABASE_URL") or "").strip())


if _database_url_configured():
    from tests.isolated_db import (  # noqa: E402
        ensure_pytest_database_url,
        is_pytest_database_name,
        rewrite_compose_postgres_host_for_local_pytest,
    )

    raw_db_url = (os.environ.get("DATABASE_URL") or "").strip()
    in_docker = Path("/.dockerenv").exists()
    if (not in_docker) and raw_db_url and "@" in raw_db_url and "@postgres:" in raw_db_url:
        os.environ.setdefault(
            "PYTEST_DATABASE_URL",
            rewrite_compose_postgres_host_for_local_pytest(raw_db_url),
        )

    ensure_pytest_database_url()
else:
    is_pytest_database_name = None  # type: ignore[assignment]

os.environ["AUTH_TEST_MODE"] = "true"
os.environ["AUTH_ENABLED"] = "true"
os.environ["BFA_CONFIRM_TEST_MODE"] = "true"
os.environ["IDP_ISSUER"] = "https://login.microsoftonline.com/test-tenant/v2.0"
os.environ["IDP_AUDIENCE"] = "test-api-audience"
os.environ["APP_ID"] = "00000000-0000-4000-8000-000000000099"
os.environ.setdefault("AYDEO_CMS_BASE_URL", "http://localhost:8000")
os.environ.setdefault("AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN", "test-internal-token")


def _require_pinned_agentstepkit() -> None:
    """Fail fast when the runtime kit does not match backend/pyproject.toml pin."""
    import importlib.metadata

    expected = "0.2.27"
    installed = importlib.metadata.version("agentstepkit")
    if installed != expected:
        pytest.exit(
            "agentstepkit "
            f"{installed} is installed but this repo pins v{expected}. "
            "Reinstall with Python 3.12+: "
            'pip install -e "./backend[dev]" '
            "or rebuild Docker: docker compose build --no-cache backend",
            returncode=2,
        )


def _require_pinned_aydeo_cms_client() -> None:
    """Fail fast when the image/venv still has pre-invoke-facts aydeo-cms-client."""
    import importlib.metadata

    expected = "0.3.0"
    installed = importlib.metadata.version("aydeo-cms-client")
    if installed != expected:
        pytest.exit(
            "aydeo-cms-client "
            f"{installed} is installed but this increment requires {expected} "
            "(CaseInvokeFactsResponse / get_case_invoke_facts). "
            "The compose volume mounts new tests onto a stale image layer. "
            "Rebuild: docker compose build --no-cache backend",
            returncode=2,
        )


def _require_pinned_aydeo_audit_sdk() -> None:
    """Fail fast when the runtime SDK does not map invoke envelope fields."""
    import importlib.metadata

    expected = "0.1.2"
    installed = importlib.metadata.version("aydeo-audit-sdk")
    if installed != expected:
        pytest.exit(
            "aydeo-audit-sdk "
            f"{installed} is installed but this repo pins {expected}. "
            "Reinstall with Python 3.12+: "
            'pip install -e "./backend[dev]" '
            "or rebuild Docker: docker compose build --no-cache backend",
            returncode=2,
        )


_require_pinned_agentstepkit()
_require_pinned_aydeo_cms_client()
_require_pinned_aydeo_audit_sdk()


def subprocess_env_without_coverage() -> dict[str, str]:
    """Drop pytest-cov process-tracking vars so child runs do not mix coverage modes."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COVERAGE")
    }


def _coverage_artifact_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _remove_parallel_coverage_artifacts() -> None:
    """Drop subprocess `.coverage.*` shards that break branch/statement combine."""
    for artifact in _coverage_artifact_dir().glob(".coverage.*"):
        artifact.unlink(missing_ok=True)


@pytest.hookimpl(trylast=False)
def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.pluginmanager.hasplugin("_cov"):
        _remove_parallel_coverage_artifacts()


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtestloop(session: pytest.Session):
    yield
    if session.config.pluginmanager.hasplugin("_cov"):
        _remove_parallel_coverage_artifacts()


def _alembic_config():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


def _require_isolated_pytest_database() -> None:
    """Fail closed if migrate/truncate would hit the demo application database."""
    from urllib.parse import urlparse

    from src.config import get_settings

    if is_pytest_database_name is None:
        pytest.exit("pytest database isolation helpers are unavailable", returncode=2)

    url = get_settings().sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://")
    db_name = (urlparse(url).path or "").strip("/").split("/")[0]
    if not is_pytest_database_name(db_name):
        pytest.exit(
            f"Refusing to migrate/truncate application database {db_name!r}; "
            "pytest must use a database name ending in '_pytest'.",
            returncode=2,
        )


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations() -> None:
    if not _database_url_configured():
        yield
        return
    from alembic import command

    from src.config import get_settings

    get_settings.cache_clear()
    _require_isolated_pytest_database()
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _truncate_db_tables(_apply_migrations: None) -> None:
    """Clear mutable domain rows between tests (after session migrations)."""
    if not _database_url_configured():
        yield
        return
    from sqlalchemy import inspect, text

    from src.db.session import get_engine

    _require_isolated_pytest_database()
    engine = get_engine()
    present = set(inspect(engine).get_table_names())
    mutable = [
        name
        for name in ("equity_order_intents", "cnb_fx_fixings", "stored_api_replies", "orders")
        if name in present
    ]
    if mutable:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{name}"' for name in mutable) + " RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    from src.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
