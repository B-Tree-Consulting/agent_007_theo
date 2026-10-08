"""Lazy SQLAlchemy session factory (mode 3 collection must not import the SQL stack)."""

from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.db import session as session_mod


@pytest.fixture(autouse=True)
def _reset_session_singletons() -> None:
    session_mod._engine = None
    session_mod._SessionLocal = None
    yield
    session_mod._engine = None
    session_mod._SessionLocal = None


def _block_sqlalchemy_imports():
    saved = {key: sys.modules[key] for key in list(sys.modules) if key == "sqlalchemy" or key.startswith("sqlalchemy.")}
    for key in saved:
        del sys.modules[key]
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "sqlalchemy" or name.startswith("sqlalchemy."):
            raise ImportError("sqlalchemy blocked")
        return real_import(name, *args, **kwargs)

    return saved, blocked


def test_get_engine_raises_when_sqlalchemy_missing() -> None:
    saved, blocked = _block_sqlalchemy_imports()
    try:
        with patch("builtins.__import__", blocked):
            with pytest.raises(RuntimeError, match=r"\[postgres\] extra"):
                session_mod.get_engine()
    finally:
        sys.modules.update(saved)


def test_session_factory_raises_when_sqlalchemy_missing() -> None:
    saved, blocked = _block_sqlalchemy_imports()
    try:
        with patch("builtins.__import__", blocked):
            with pytest.raises(RuntimeError, match=r"\[postgres\] extra"):
                session_mod._session_factory()
    finally:
        sys.modules.update(saved)


def test_get_engine_creates_once() -> None:
    engine = object()
    create_engine = MagicMock(return_value=engine)
    fake_sqlalchemy = SimpleNamespace(create_engine=create_engine)
    settings = SimpleNamespace(sqlalchemy_url="postgresql+psycopg://u:p@localhost/db")
    with (
        patch.dict(sys.modules, {"sqlalchemy": fake_sqlalchemy}),
        patch("src.db.session.get_settings", return_value=settings),
    ):
        assert session_mod.get_engine() is engine
        assert session_mod.get_engine() is engine
    create_engine.assert_called_once()


def test_session_local_proxy_and_get_session() -> None:
    bound = MagicMock()
    factory = MagicMock(return_value=bound)
    fake_orm = SimpleNamespace(sessionmaker=MagicMock(return_value=factory))
    engine = object()
    with (
        patch.dict(sys.modules, {"sqlalchemy.orm": fake_orm}),
        patch("src.db.session.get_engine", return_value=engine),
    ):
        session_mod._SessionLocal = None
        gen = session_mod.get_session()
        yielded = next(gen)
        assert yielded is bound
        factory.assert_called_once_with(bind=engine)
        gen.close()
        bound.close.assert_called_once()
