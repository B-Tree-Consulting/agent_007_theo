#!/usr/bin/env python3
"""Strip local Postgres from a bootstrapped demo host (no-pizza path).

Used by scripts/bootstrap-new-host.sh when pizza is stripped and the operator
opts out of compose Postgres. Host shell does not require SQL; domain stores
that need a DB must re-add Postgres + DATABASE_URL later.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_DEPENDS_ON = re.compile(
    r"\n[ \t]*depends_on:\n[ \t]*postgres:\n[ \t]*condition:[^\n]+\n"
)
_POSTGRES_SERVICE = re.compile(
    r"\n[ \t]*postgres:\n(?:[ \t]+[^\n]*\n)+"
)
_VOLUMES = re.compile(r"\nvolumes:\n(?:[ \t]+[^\n]*\n)+")

_DATABASE_URL_FIELD = re.compile(
    r"^([ \t]*)database_url:[ \t]*str\s*$",
    re.MULTILINE,
)
_SQLALCHEMY_URL_PROP = re.compile(
    r"([ \t]*)@property\n"
    r"([ \t]*)def sqlalchemy_url\(self\) -> str:\n"
    r"([ \t]*)url = self\.database_url\.strip\(\)\n",
)

_ENV_PG_SECTION = re.compile(
    r"# =+\n# PostgreSQL \(docker-compose \+ backend\)\n# =+\n"
    r"POSTGRES_USER=.*\n"
    r"POSTGRES_PASSWORD=.*\n"
    r"POSTGRES_DB=.*\n"
    r"POSTGRES_HOST=.*\n"
    r"\n"
    r"# =+\n# Database \(backend\)\n# =+\n"
    r"DATABASE_URL=.*\n",
)

_OPTIONAL_DB_ENV = """# =============================================================================
# PostgreSQL / Database (optional — compose has no Postgres after bootstrap strip)
# =============================================================================
# Re-enable when your domain needs local SQL: restore the postgres service in
# docker-compose.yml, set these, then alembic upgrade head.
# POSTGRES_USER=your-slug
# POSTGRES_PASSWORD=changeme-generate-strong-password
# POSTGRES_DB=your-slug
# POSTGRES_HOST=postgres
# DATABASE_URL=postgresql://your-slug:changeme-generate-strong-password@postgres:5432/your-slug
"""


def strip_postgres_from_compose(text: str) -> str:
    out = _DEPENDS_ON.sub("\n", text, count=1)
    out = _POSTGRES_SERVICE.sub("\n", out, count=1)
    out = _VOLUMES.sub("\n", out, count=1)
    if re.search(r"^[ \t]*postgres:", out, re.MULTILINE):
        raise ValueError("postgres service remains after compose strip")
    if re.search(r"^[ \t]*depends_on:", out, re.MULTILINE):
        raise ValueError("depends_on remains after compose strip")
    if re.search(r"^volumes:", out, re.MULTILINE):
        raise ValueError("top-level volumes remain after compose strip")
    if "backend:" not in out:
        raise ValueError("backend service missing after compose strip")
    return out.rstrip() + "\n"


def strip_postgres_from_config(text: str) -> str:
    if not _DATABASE_URL_FIELD.search(text):
        raise ValueError("database_url: str field not found in config.py")
    out = _DATABASE_URL_FIELD.sub(
        r"\1database_url: str | None = None  # optional when compose has no Postgres",
        text,
        count=1,
    )
    if not _SQLALCHEMY_URL_PROP.search(out):
        raise ValueError("sqlalchemy_url property shape not found in config.py")
    out = _SQLALCHEMY_URL_PROP.sub(
        r"\1@property\n"
        r"\2def sqlalchemy_url(self) -> str:\n"
        r"\3if not self.database_url or not str(self.database_url).strip():\n"
        r"\3    raise ValueError(\n"
        r'\3        "DATABASE_URL is not set — restore Postgres in compose when your domain needs a database"\n'
        r"\3    )\n"
        r"\3url = self.database_url.strip()\n",
        out,
        count=1,
    )
    return out


def strip_postgres_from_env_example(text: str) -> str:
    if not _ENV_PG_SECTION.search(text):
        raise ValueError("PostgreSQL / Database sections not found in .env.example")
    return _ENV_PG_SECTION.sub(_OPTIONAL_DB_ENV + "\n", text, count=1)


_DEFAULT_DB_URL_BLOCK = re.compile(
    r"# BEGIN_DEFAULT_DATABASE_URL\n.*?# END_DEFAULT_DATABASE_URL\n",
    re.DOTALL,
)

_SQLALCHEMY_DEPS = re.compile(
    r'\n[ \t]*"sqlalchemy>=2\.0,<3",\n[ \t]*"alembic>=1\.13,<2",\n[ \t]*"psycopg\[binary\]>=3\.1,<4",'
)

_DOCKER_SQL_PACKAGES = (
    '"sqlalchemy>=2.0,<3" ',
    '"alembic>=1.13,<2" ',
    '"psycopg[binary]>=3.1,<4" ',
)


def strip_postgres_from_conftest(text: str) -> str:
    if "# BEGIN_DEFAULT_DATABASE_URL" not in text:
        raise ValueError("DEFAULT DATABASE_URL block not found in conftest.py")
    out = _DEFAULT_DB_URL_BLOCK.sub("", text, count=1)
    return out


def strip_postgres_from_pyproject(text: str) -> str:
    if not _SQLALCHEMY_DEPS.search(text):
        raise ValueError("sqlalchemy/alembic/psycopg dependencies not found in pyproject.toml")
    out = _SQLALCHEMY_DEPS.sub("", text, count=1)
    extra = (
        "\npostgres = [\n"
        '  "sqlalchemy>=2.0,<3",\n'
        '  "alembic>=1.13,<2",\n'
        '  "psycopg[binary]>=3.1,<4",\n'
        "]\n"
    )
    marker = "[project.optional-dependencies]\n"
    if marker not in out:
        raise ValueError("optional-dependencies section missing in pyproject.toml")
    if "postgres = [" not in out:
        out = out.replace(marker, marker + extra, 1)
    return out


def strip_postgres_from_dockerfile(text: str) -> str:
    out = text
    for pkg in _DOCKER_SQL_PACKAGES:
        out = out.replace(pkg, "")
    if "sqlalchemy>=" in out or "alembic>=" in out or "psycopg[binary]" in out:
        raise ValueError("sqlalchemy/alembic/psycopg remain in Dockerfile")
    return out


def strip_postgres_from_readme(text: str) -> str:
    note = (
        "Postgres is stripped from this generated host. Restore the compose "
        "`postgres` service, install the `[postgres]` extra (`sqlalchemy` / "
        "`alembic` / `psycopg`), set `DATABASE_URL`, and re-add Alembic versions "
        "before running `./scripts/greenfield-alembic-test.sh`.\n"
    )
    out = text.replace("./scripts/greenfield-alembic-test.sh", "# greenfield-alembic-test.sh omitted until Postgres is restored")
    if "Postgres is stripped from this generated host" not in out:
        out = note + "\n" + out
    return out


def strip_postgres_from_repo(root: Path) -> None:
    compose = root / "docker-compose.yml"
    config = root / "backend" / "src" / "config.py"
    env_example = root / "backend" / ".env.example"
    versions = root / "backend" / "migrations" / "versions"
    conftest = root / "backend" / "tests" / "conftest.py"
    pyproject = root / "backend" / "pyproject.toml"
    dockerfile = root / "backend" / "Dockerfile"

    compose.write_text(strip_postgres_from_compose(compose.read_text(encoding="utf-8")), encoding="utf-8")
    config.write_text(strip_postgres_from_config(config.read_text(encoding="utf-8")), encoding="utf-8")
    env_example.write_text(
        strip_postgres_from_env_example(env_example.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    if conftest.is_file():
        conftest.write_text(strip_postgres_from_conftest(conftest.read_text(encoding="utf-8")), encoding="utf-8")
    if pyproject.is_file():
        pyproject.write_text(strip_postgres_from_pyproject(pyproject.read_text(encoding="utf-8")), encoding="utf-8")
    if dockerfile.is_file():
        dockerfile.write_text(strip_postgres_from_dockerfile(dockerfile.read_text(encoding="utf-8")), encoding="utf-8")

    readme = root / "README.md"
    if readme.is_file():
        readme.write_text(strip_postgres_from_readme(readme.read_text(encoding="utf-8")), encoding="utf-8")

    if versions.is_dir():
        for path in versions.glob("*.py"):
            path.unlink()

    db_tests = root / "backend" / "tests" / "db"
    if db_tests.is_dir():
        shutil.rmtree(db_tests)
    isolated = root / "backend" / "tests" / "test_isolated_db.py"
    if isolated.is_file():
        isolated.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repo_root",
        type=Path,
        help="Target host repo root (contains docker-compose.yml)",
    )
    args = parser.parse_args(argv)
    root = args.repo_root
    if not (root / "docker-compose.yml").is_file():
        print(f"error: docker-compose.yml not found under {root}", file=sys.stderr)
        return 1
    try:
        strip_postgres_from_repo(root)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Stripped Postgres from {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
