"""Per-request context for blueprint adapters."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Generator

_UNSET: Any = object()

_entra_token: ContextVar[str | None] = ContextVar("bfa_host_entra_token", default=None)
_runtime_de_id: ContextVar[str | None] = ContextVar("bfa_host_runtime_de_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("bfa_host_correlation_id", default=None)


@dataclass(frozen=True)
class RuntimeRequestScope:
    entra_token: str | None = None
    runtime_de_id: str | None = None
    correlation_id: str | None = None


def get_runtime_request_scope() -> RuntimeRequestScope:
    return RuntimeRequestScope(
        entra_token=_entra_token.get(),
        runtime_de_id=_runtime_de_id.get(),
        correlation_id=_correlation_id.get(),
    )


def get_runtime_de_id() -> str | None:
    value = _runtime_de_id.get()
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def set_runtime_de_id(de_id: str | None) -> None:
    _runtime_de_id.set((de_id or "").strip() or None)


@contextmanager
def set_runtime_request_context(
    *,
    entra_token: str | None = None,
    correlation_id: Any = _UNSET,
) -> Generator[None, None, None]:
    tokens: list[tuple[ContextVar[Any], Any]] = []
    if entra_token is not None:
        tokens.append((_entra_token, _entra_token.set(entra_token)))
    tokens.append((_runtime_de_id, _runtime_de_id.set(None)))
    if correlation_id is not _UNSET:
        tokens.append((_correlation_id, _correlation_id.set(correlation_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
