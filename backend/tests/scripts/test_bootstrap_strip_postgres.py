"""Unit tests for bootstrap Postgres-strip helper (sample#33)."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND.parent
_HELPER = _REPO_ROOT / "scripts" / "bootstrap_strip_postgres.py"

sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from bootstrap_strip_postgres import (  # noqa: E402
    strip_postgres_from_compose,
    strip_postgres_from_config,
    strip_postgres_from_conftest,
    strip_postgres_from_dockerfile,
    strip_postgres_from_env_example,
    strip_postgres_from_pyproject,
    strip_postgres_from_readme,
    strip_postgres_from_repo,
)


@pytest.fixture(scope="module")
def compose_source() -> str:
    path = _REPO_ROOT / "docker-compose.yml"
    if not path.is_file():
        pytest.fail(
            f"docker-compose.yml not found at {path}. "
            "When running pytest in Docker, mount it at /app/docker-compose.yml "
            "(see docker-compose.yml volumes) or rebuild the image."
        )
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config_source() -> str:
    return (_BACKEND / "src" / "config.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def env_example_source() -> str:
    return (_BACKEND / ".env.example").read_text(encoding="utf-8")


def test_compose_strip_removes_postgres(compose_source: str) -> None:
    if "postgres:" not in compose_source:
        pytest.skip("postgres already stripped in this tree")
    out = strip_postgres_from_compose(compose_source)
    assert not any(line.startswith("  postgres:") or line.startswith("postgres:") for line in out.splitlines())
    assert "depends_on:" not in out
    assert not any(line.strip() == "volumes:" and not line.startswith(" ") for line in out.splitlines())
    assert not re.search(r"^volumes:", out, re.MULTILINE)
    assert "backend:" in out
    assert "8015:8000" in out
    # bind mounts under backend remain
    assert "./backend:/app/backend" in out


def test_config_strip_makes_database_url_optional(config_source: str) -> None:
    if "database_url: str | None" in config_source:
        pytest.skip("database_url already optional in this tree")
    out = strip_postgres_from_config(config_source)
    ast.parse(out)
    assert "database_url: str | None = None" in out
    assert "DATABASE_URL is not set" in out
    assert "url = self.database_url.strip()" in out


def test_env_example_strip_comments_db(env_example_source: str) -> None:
    if "optional — compose has no Postgres" in env_example_source:
        pytest.skip("env example already stripped in this tree")
    out = strip_postgres_from_env_example(env_example_source)
    assert "optional — compose has no Postgres" in out
    assert not any(
        line.startswith("DATABASE_URL=") and not line.strip().startswith("#")
        for line in out.splitlines()
    )
    assert "GITHUB_TOKEN" in out or "Authentication" in out


def test_strip_repo_tmp(tmp_path: Path, compose_source: str, config_source: str, env_example_source: str) -> None:
    if "postgres:" not in compose_source or "# BEGIN_DEFAULT_DATABASE_URL" not in (
        _BACKEND / "tests" / "conftest.py"
    ).read_text(encoding="utf-8"):
        pytest.skip("live tree already postgres-stripped; tmp copies would not match helper shapes")
    (tmp_path / "docker-compose.yml").write_text(compose_source, encoding="utf-8")
    backend = tmp_path / "backend"
    src = backend / "src"
    versions = backend / "migrations" / "versions"
    tests = backend / "tests"
    src.mkdir(parents=True)
    versions.mkdir(parents=True)
    (tests / "db").mkdir(parents=True)
    (src / "config.py").write_text(config_source, encoding="utf-8")
    (backend / ".env.example").write_text(env_example_source, encoding="utf-8")
    (versions / "0001_initial.py").write_text("# migration\n", encoding="utf-8")
    (tests / "conftest.py").write_text((_BACKEND / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    (backend / "pyproject.toml").write_text((_BACKEND / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")
    (backend / "Dockerfile").write_text((_BACKEND / "Dockerfile").read_text(encoding="utf-8"), encoding="utf-8")
    (tests / "db" / "test_migrations.py").write_text("# db\n", encoding="utf-8")
    (tests / "test_isolated_db.py").write_text("# isolated\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Run ./scripts/greenfield-alembic-test.sh\n", encoding="utf-8")

    strip_postgres_from_repo(tmp_path)

    compose = (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgres:" not in compose
    assert "database_url: str | None = None" in (src / "config.py").read_text(encoding="utf-8")
    assert list(versions.glob("*.py")) == []
    conftest = (tests / "conftest.py").read_text(encoding="utf-8")
    assert "BEGIN_DEFAULT_DATABASE_URL" not in conftest
    assert "setdefault(\"DATABASE_URL\"" not in conftest
    pyproject = (backend / "pyproject.toml").read_text(encoding="utf-8")
    assert "sqlalchemy>=2.0,<3" not in pyproject.split("[project.optional-dependencies]")[0]
    assert "postgres = [" in pyproject
    dockerfile = (backend / "Dockerfile").read_text(encoding="utf-8")
    assert "sqlalchemy>=" not in dockerfile
    assert "alembic>=" not in dockerfile
    assert "psycopg[binary]" not in dockerfile
    assert not (tests / "db").exists()
    assert not (tests / "test_isolated_db.py").exists()
    assert "Postgres is stripped" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_conftest_strip_removes_default_url() -> None:
    src = (_BACKEND / "tests" / "conftest.py").read_text(encoding="utf-8")
    if "# BEGIN_DEFAULT_DATABASE_URL" not in src:
        pytest.skip("conftest already stripped in this tree")
    out = strip_postgres_from_conftest(src)
    assert "BEGIN_DEFAULT_DATABASE_URL" not in out
    assert "ensure_pytest_database_url()" in out


def test_conftest_strip_rejects_missing_block() -> None:
    with pytest.raises(ValueError, match="DEFAULT DATABASE_URL"):
        strip_postgres_from_conftest("import os\n")


def test_pyproject_moves_sql_to_extra() -> None:
    src = (_BACKEND / "pyproject.toml").read_text(encoding="utf-8")
    if "postgres = [" in src:
        pytest.skip("pyproject already has [postgres] extra")
    out = strip_postgres_from_pyproject(src)
    main, extra = out.split("[project.optional-dependencies]", 1)
    assert "sqlalchemy>=2.0,<3" not in main
    assert "postgres = [" in extra
    assert "psycopg[binary]>=3.1,<4" in extra


def test_pyproject_rejects_missing_deps() -> None:
    with pytest.raises(ValueError, match="sqlalchemy/alembic/psycopg"):
        strip_postgres_from_pyproject("[project]\ndependencies = []\n[project.optional-dependencies]\ndev = []\n")


def test_dockerfile_strips_sql_packages() -> None:
    src = (_BACKEND / "Dockerfile").read_text(encoding="utf-8")
    if "sqlalchemy>=" not in src:
        pytest.skip("Dockerfile already stripped in this tree")
    out = strip_postgres_from_dockerfile(src)
    assert "sqlalchemy>=" not in out
    assert "alembic>=" not in out
    assert "psycopg[binary]" not in out


def test_dockerfile_rejects_leftover_sql() -> None:
    with pytest.raises(ValueError, match="remain in Dockerfile"):
        strip_postgres_from_dockerfile('pip install "sqlalchemy>=2.0,<3"\n')


def test_readme_strip_documents_restore() -> None:
    out = strip_postgres_from_readme("See ./scripts/greenfield-alembic-test.sh\n")
    assert "Postgres is stripped from this generated host" in out
    assert "greenfield-alembic-test.sh omitted" in out


def test_compose_rejects_leftover_postgres_service() -> None:
    # Empty postgres key does not match the multi-line service stripper.
    with pytest.raises(ValueError, match="postgres service remains"):
        strip_postgres_from_compose("services:\n  backend:\n    image: x\n  postgres:\n")


def test_compose_rejects_leftover_depends_on() -> None:
    with pytest.raises(ValueError, match="depends_on remains"):
        strip_postgres_from_compose(
            "services:\n  backend:\n    depends_on:\n      - redis\n    image: x\n"
        )


def test_compose_rejects_leftover_top_level_volumes() -> None:
    with pytest.raises(ValueError, match="top-level volumes remain"):
        strip_postgres_from_compose("services:\n  backend:\n    image: x\n\nvolumes:\n")


def test_compose_rejects_missing_backend() -> None:
    with pytest.raises(ValueError, match="backend service missing"):
        strip_postgres_from_compose("services:\n  api:\n    image: x\n")


def test_config_rejects_missing_sqlalchemy_prop() -> None:
    with pytest.raises(ValueError, match="sqlalchemy_url"):
        strip_postgres_from_config("class Settings:\n    database_url: str\n")


def test_env_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        strip_postgres_from_env_example("# no db sections\nAUTH_ENABLED=true\n")


def test_cli_entrypoint_as_main(
    tmp_path: Path, compose_source: str, config_source: str, env_example_source: str
) -> None:
    if "postgres:" not in compose_source:
        pytest.skip("postgres already stripped in this tree")
    import runpy

    (tmp_path / "docker-compose.yml").write_text(compose_source, encoding="utf-8")
    backend = tmp_path / "backend" / "src"
    backend.mkdir(parents=True)
    (tmp_path / "backend" / "migrations" / "versions").mkdir(parents=True)
    (backend / "config.py").write_text(config_source, encoding="utf-8")
    (tmp_path / "backend" / ".env.example").write_text(env_example_source, encoding="utf-8")

    old_argv = sys.argv
    try:
        sys.argv = [str(_HELPER), str(tmp_path)]
        with pytest.raises(SystemExit) as exited:
            runpy.run_path(str(_HELPER), run_name="__main__")
        assert exited.value.code == 0
    finally:
        sys.argv = old_argv


def test_main_cli_transform_error(tmp_path: Path) -> None:
    import bootstrap_strip_postgres as mod

    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    image: x\n", encoding="utf-8")
    assert mod.main([str(tmp_path)]) == 1


def test_helper_script_exists() -> None:
    assert _HELPER.is_file()
