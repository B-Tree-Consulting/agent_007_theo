"""Database engine and session factory."""

from collections.abc import Iterator

from src.config import get_settings

_engine = None
_SessionLocal = None


def get_engine():
    """Lazy singleton SQLAlchemy engine."""
    global _engine
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "SQLAlchemy is not installed — restore the [postgres] extra when the domain needs a database"
        ) from exc
    if _engine is None:
        _engine = create_engine(
            get_settings().sqlalchemy_url,
            pool_pre_ping=True,
        )
    return _engine


def _session_factory():
    global _SessionLocal
    try:
        from sqlalchemy.orm import sessionmaker
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "SQLAlchemy is not installed — restore the [postgres] extra when the domain needs a database"
        ) from exc
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SessionLocal


class _LazySessionLocal:
    def __call__(self, *args, **kwargs):
        return _session_factory()(*args, **kwargs)


SessionLocal = _LazySessionLocal()


def get_session() -> Iterator[object]:
    """FastAPI dependency yielding a DB session."""
    session = SessionLocal(bind=get_engine())
    try:
        yield session
    finally:
        session.close()
