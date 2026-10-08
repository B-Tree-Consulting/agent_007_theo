"""Per-invoke case id for domain tools that cannot take case_id as an input."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

_case_id: ContextVar[str | None] = ContextVar("invoke_case_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("invoke_correlation_id", default=None)
_approval_record_id: ContextVar[str | None] = ContextVar("invoke_approval_record_id", default=None)
_account_reads: ContextVar[dict | None] = ContextVar("invoke_account_reads", default=None)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def get_invoke_case_id() -> str | None:
    return _clean(_case_id.get())


def get_invoke_correlation_id() -> str | None:
    return _clean(_correlation_id.get())


def get_invoke_approval_record_id() -> str | None:
    return _clean(_approval_record_id.get())


def get_invoke_account_cache() -> dict | None:
    """Broker reads reused for the rest of this invoke. Absent outside an invoke."""
    return _account_reads.get()


@contextmanager
def bind_invoke_case_id(
    case_id: str | None,
    correlation_id: str | None = None,
    approval_record_id: str | None = None,
) -> Iterator[None]:
    case_token = _case_id.set(_clean(case_id))
    correlation_token = _correlation_id.set(_clean(correlation_id))
    approval_token = _approval_record_id.set(_clean(approval_record_id))
    cache_token = _account_reads.set({})
    try:
        yield
    finally:
        _account_reads.reset(cache_token)
        _approval_record_id.reset(approval_token)
        _correlation_id.reset(correlation_token)
        _case_id.reset(case_token)
