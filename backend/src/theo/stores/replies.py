"""Database rows for StoredReply outbound reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.db.session import SessionLocal, get_engine
from src.theo.models import StoredApiReply


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session():
    return SessionLocal(bind=get_engine())


def get_reply(provider: str, route: str, subject: str) -> StoredApiReply | None:
    session = _session()
    try:
        row = session.query(StoredApiReply).filter_by(provider=provider, route=route, subject=subject).one_or_none()
        if row is not None:
            session.expunge(row)
        return row
    finally:
        session.close()


def blocking_reply(provider: str, route: str, subject: str, *, now: datetime | None = None) -> StoredApiReply | None:
    """Return the row while the provider told us not to call, even if it has no payload yet."""
    row = get_reply(provider, route, subject)
    if row is None or row.cooldown_until is None:
        return None
    current = now or _now()
    if row.cooldown_until > current:
        return row
    return None


def remember_success(provider: str, route: str, subject: str, payload: Any, *, fetched_at: datetime | None = None) -> StoredApiReply:
    session = _session()
    try:
        row = session.query(StoredApiReply).filter_by(provider=provider, route=route, subject=subject).one_or_none()
        when = fetched_at or _now()
        if row is None:
            row = StoredApiReply(provider=provider, route=route, subject=subject)
            session.add(row)
        row.payload = payload
        row.fetched_at = when
        row.cooldown_until = None
        session.commit()
        session.refresh(row)
        return row
    finally:
        session.close()


def remember_cooldown(
    provider: str,
    route: str,
    subject: str,
    seconds: float,
    *,
    now: datetime | None = None,
) -> None:
    """Record how long to wait. Does not replace a stored payload."""
    session = _session()
    try:
        row = session.query(StoredApiReply).filter_by(provider=provider, route=route, subject=subject).one_or_none()
        current = now or _now()
        if row is None:
            row = StoredApiReply(provider=provider, route=route, subject=subject, payload=None)
            session.add(row)
        row.cooldown_until = current + timedelta(seconds=max(seconds, 0.0))
        session.commit()
    finally:
        session.close()
