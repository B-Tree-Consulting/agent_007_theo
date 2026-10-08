"""Alembic migration smoke tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text


def _cfg() -> Config:
    backend_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


HEAD_REVISION = "0003_intent_correlation"


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
