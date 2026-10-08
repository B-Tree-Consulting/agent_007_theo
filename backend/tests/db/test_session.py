"""Database session factory tests."""

from sqlalchemy import text

from src.db import session as db_session


def test_get_engine_is_singleton() -> None:
    db_session._engine = None
    first = db_session.get_engine()
    second = db_session.get_engine()
    assert first is second


def test_get_session_yields_connection_and_closes() -> None:
    db_session._engine = None
    gen = db_session.get_session()
    db = next(gen)
    try:
        assert db.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        gen.close()
