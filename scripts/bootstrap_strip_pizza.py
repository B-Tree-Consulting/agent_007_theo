#!/usr/bin/env python3
"""Strip pizza sample registration from host factory.py (bootstrap helper).

Used by scripts/bootstrap-new-host.sh. Keeps empty-tool hard fails: after strip,
callers must register domain tools before starting the host.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

_REGISTER_STUB = '''def register_sample_modules() -> None:
    """Register domain modules — wire your bootstrap here before starting the host.

    Host startup hard-fails when no tools are registered (path A). Call your
    ``register_*_tools(HostSampleBFA)`` from this function, then compose up.
    """
    pass
'''

_CATALOG_IMPORT = re.compile(
    r"\n[ \t]*from src\.samples\.pizza\.catalog_metadata import PizzaCatalogMetadataProvider\n"
)
_CATALOG_KWARG = re.compile(
    r",\n[ \t]*catalog_metadata_provider=PizzaCatalogMetadataProvider\(\)"
)
# Match full register_sample_modules through the function body until the next top-level def.
_REGISTER_FN = re.compile(
    r"^def register_sample_modules\(\) -> None:.*?(?=^def )",
    re.MULTILINE | re.DOTALL,
)


def strip_pizza_from_factory_source(text: str) -> str:
    """Return factory.py source with pizza registration and catalog metadata removed."""
    if not _REGISTER_FN.search(text):
        raise ValueError("register_sample_modules() not found in factory source")

    out = _REGISTER_FN.sub(_REGISTER_STUB + "\n", text, count=1)
    out = _CATALOG_IMPORT.sub("\n", out)
    out = _CATALOG_KWARG.sub("", out)

    if "samples.pizza" in out or "PizzaCatalogMetadataProvider" in out or "register_pizza_tools" in out:
        raise ValueError("pizza references remain after strip transform")
    if out.count("build_aydeo_host(") < 2:
        raise ValueError("expected both build_aydeo_host call sites to remain")

    ast.parse(out)
    return out


def strip_pizza_from_factory_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(strip_pizza_from_factory_source(text), encoding="utf-8")


_EMPTY_REVISION = '''"""Host-neutral empty schema (no domain tables).

Revision ID: 0001_empty
Revises:
"""

from typing import Sequence, Union

revision: str = "0001_empty"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
'''

_MIGRATION_TESTS = '''"""Alembic migration smoke tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text


def _cfg() -> Config:
    backend_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


HEAD_REVISION = "0001_empty"


def test_upgrade_from_empty_records_revision() -> None:
    engine = __import__("src.db.session", fromlist=["get_engine"]).get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).one_or_none()
    assert row is not None
    assert row.version_num == HEAD_REVISION


def test_upgrade_has_no_domain_tables() -> None:
    engine = __import__("src.db.session", fromlist=["get_engine"]).get_engine()
    tables = set(inspect(engine).get_table_names())
    assert "menu_items" not in tables
    assert "orders" not in tables


def test_downgrade_then_upgrade_restores_revision() -> None:
    cfg = _cfg()
    try:
        command.downgrade(cfg, "base")
        engine = __import__("src.db.session", fromlist=["get_engine"]).get_engine()
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).one_or_none()
        assert row is None
    finally:
        command.upgrade(cfg, "head")
        engine = __import__("src.db.session", fromlist=["get_engine"]).get_engine()
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).one_or_none()
        assert row is not None
        assert row.version_num == HEAD_REVISION
'''

_MODELS_INIT = '''"""SQLAlchemy ORM models."""

from src.db.models.base import Base

__all__ = ["Base"]
'''

_DELETE_RELATIVE = (
    "backend/src/samples/pizza",
    "backend/tests/samples/pizza",
    "backend/tests/host/test_bfa_flow_smoke.py",
    "backend/tests/host/test_bfa_host.py",
    "backend/tests/host/test_flow_helpers.py",
    "backend/tests/host/flow_helpers.py",
)

_PIZZA_PHRASES: tuple[tuple[str, str], ...] = (
    ("PizzaCatalogMetadataProvider", "CatalogMetadataProvider"),
    ("register_pizza_tools", "register_domain_tools"),
    ("order_pizza_for_event", "domain_action_high_event"),
    ("order_pizza_for_team", "domain_action_high_team"),
    ("order_pizza_for_me", "domain_action_medium"),
    ("samples/pizza", "samples/<domain>"),
    ("src.samples.pizza", "src.samples.domain"),
    ("BFA → Pizza", "BFA → Domain"),
    ("**BFA → Pizza**", "**BFA → Domain**"),
    ("sample_menu_ref", "sample_item_ref"),
    ("PIZZA_DOMAIN", "DOMAIN"),
    ("get_menu", "domain_query"),
)


def neutralize_pizza_text(text: str) -> str:
    out = text
    for old, new in _PIZZA_PHRASES:
        out = out.replace(old, new)
    out = re.sub(r"(?i)pizza", "domain", out)
    return out


def _rm(path: Path) -> None:
    import shutil

    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()


def _strip_postman_collection(path: Path) -> None:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("item") or []
    data["item"] = [item for item in items if str(item.get("name", "")).lower() != "pizza"]
    nested = []
    for item in data["item"]:
        if isinstance(item, dict) and item.get("item"):
            item["item"] = [
                child
                for child in item["item"]
                if "pizza" not in str(child.get("name", "")).lower()
            ]
        nested.append(item)
    data["item"] = nested
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _strip_postman_environment(path: Path) -> None:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    drop = {"sample_menu_ref", "sample_event_date", "order_ref"}
    data["values"] = [row for row in data.get("values") or [] if row.get("key") not in drop]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _replace_migrations(versions: Path) -> None:
    if not versions.is_dir():
        return
    for path in versions.glob("*.py"):
        path.unlink()
    (versions / "0001_empty.py").write_text(_EMPTY_REVISION, encoding="utf-8")


def strip_pizza_from_repo(root: Path) -> None:
    """Repo-root pizza strip used by bootstrap-new-host.sh."""
    for rel in _DELETE_RELATIVE:
        _rm(root / rel)

    factory = root / "backend" / "src" / "host" / "factory.py"
    strip_pizza_from_factory_file(factory)

    models = root / "backend" / "src" / "db" / "models" / "__init__.py"
    if models.is_file():
        models.write_text(_MODELS_INIT, encoding="utf-8")

    _replace_migrations(root / "backend" / "migrations" / "versions")
    migration_tests = root / "backend" / "tests" / "db" / "test_migrations.py"
    if migration_tests.is_file():
        migration_tests.write_text(_MIGRATION_TESTS, encoding="utf-8")

    main_py = root / "backend" / "src" / "main.py"
    if main_py.is_file():
        main_py.write_text(neutralize_pizza_text(main_py.read_text(encoding="utf-8")), encoding="utf-8")

    facade = root / "backend" / "src" / "host" / "facade.py"
    if facade.is_file():
        facade.write_text(neutralize_pizza_text(facade.read_text(encoding="utf-8")), encoding="utf-8")

    host_readme = root / "backend" / "src" / "host" / "README.md"
    if host_readme.is_file():
        host_readme.write_text(neutralize_pizza_text(host_readme.read_text(encoding="utf-8")), encoding="utf-8")

    for rel in ("README.md", "POSTMAN_GUIDE.md"):
        path = root / rel
        if path.is_file():
            path.write_text(neutralize_pizza_text(path.read_text(encoding="utf-8")), encoding="utf-8")

    collection = root / "postman" / "collection.json"
    if collection.is_file():
        _strip_postman_collection(collection)
        collection.write_text(neutralize_pizza_text(collection.read_text(encoding="utf-8")), encoding="utf-8")
    env = root / "postman" / "environment.json"
    if env.is_file():
        _strip_postman_environment(env)

    host_tests = root / "backend" / "tests" / "host"
    if host_tests.is_dir():
        for path in host_tests.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md"}:
                text = path.read_text(encoding="utf-8")
                if re.search(r"(?i)pizza", text):
                    path.write_text(neutralize_pizza_text(text), encoding="utf-8")

    src_root = root / "backend" / "src"
    if src_root.is_dir():
        for path in src_root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md"}:
                continue
            if "samples" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"(?i)pizza", text):
                path.write_text(neutralize_pizza_text(text), encoding="utf-8")

    samples = root / "backend" / "src" / "samples"
    if samples.is_dir() and not any(p.is_dir() and p.name != "__pycache__" for p in samples.iterdir()):
        import shutil

        shutil.rmtree(samples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="Repo root (full strip) or backend/src/host/factory.py (factory-only)",
    )
    args = parser.parse_args(argv)
    target = args.target
    try:
        if target.is_dir():
            if not (target / "backend" / "src" / "host" / "factory.py").is_file():
                print(f"error: factory.py not found under {target}", file=sys.stderr)
                return 1
            strip_pizza_from_repo(target)
            print(f"Stripped pizza sample from {target}")
            return 0
        if target.is_file():
            strip_pizza_from_factory_file(target)
            print(f"Patched {target}")
            return 0
    except (ValueError, SyntaxError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"error: not a file or directory: {target}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

