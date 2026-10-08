"""BFA facade shell for the host sample (domain tools register via bootstrap)."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from bfa import BFA, CallContext, TokenIntrospector
from bfa.resolvers import SimpleResolver
from episodicmemory import NullEpisodeLogger

from src.config import get_settings
from src.host.case_comment_client import CaseCommentClient
from src.host.outbox_factory import build_host_outbox

# Kit BFA shell requires employee_id at construction (episodes only). Audit digital_employee_id is capability de_id.
_FACADE_SHELL_PLACEHOLDER_DE_ID = "00000000-0000-0000-0000-000000000000"


class _UnusedTokenIntrospector(TokenIntrospector):
    def introspect(self, token: str, *, correlation_id: Optional[str] = None):
        raise RuntimeError("token introspection is not used on the blueprint runtime path")


def _case_comments_for_call(ctx: CallContext) -> CaseCommentClient:
    settings = get_settings()
    return CaseCommentClient(base_url=settings.aydeo_cms_base_url, bearer=ctx.token)


class HostSampleBFA(BFA):
    """Minimal BFA shell; sample business tools attach via ``register_sample_modules()``."""

    pass


@lru_cache
def _get_host_bfa_cached() -> HostSampleBFA:
    settings = get_settings()
    shell_employee_id = (
        settings.bfa_test_de_id
        if settings.auth_test_mode or not settings.auth_enabled
        else _FACADE_SHELL_PLACEHOLDER_DE_ID
    )
    return HostSampleBFA(
        employee_id=shell_employee_id,
        resolver=SimpleResolver(providers={"case_comments": _case_comments_for_call}),
        token_introspector=_UnusedTokenIntrospector(),
        outbox=build_host_outbox(),
        episode_logger=NullEpisodeLogger(),
    )


def get_host_bfa() -> HostSampleBFA:
    """Return the cached BFA shell; sample tools register before first construction."""
    from src.host.factory import register_sample_modules

    register_sample_modules()
    facade = _get_host_bfa_cached()
    if facade.tools():
        return facade
    # Defensive: kit binds class tool specs at construction; rebuild if cached too early.
    _get_host_bfa_cached.cache_clear()
    register_sample_modules()
    facade = _get_host_bfa_cached()
    if not facade.tools():
        raise RuntimeError(
            "BFA host facade has no registered tools after sample bootstrap",
        )
    return facade


get_host_bfa.cache_clear = _get_host_bfa_cached.cache_clear  # type: ignore[attr-defined]
