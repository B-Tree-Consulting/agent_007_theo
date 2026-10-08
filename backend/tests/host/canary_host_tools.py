"""Register/teardown test-only canary tools on HostSampleBFA.

Never imported from production factory or main. Sample-domain presence is detected by
whether ``src/samples/`` still has a domain package, not a production env flag.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from tests.fixtures.case_policy_parity import canary_tools

_FLAG = "_aydeo_host_canaries_registered"
_CANARY_ATTRS = (
    canary_tools.CANARY_ACTION_DIRECT,
    canary_tools.CANARY_ACTION_REFERENCE,
    canary_tools.CANARY_ACTION_MEDIUM,
    canary_tools.CANARY_QUERY_BOUNDED,
)
_CANARY_NAMES = frozenset(_CANARY_ATTRS)


def sample_domain_bootstrap_present() -> bool:
    samples_root = Path(__file__).resolve().parents[2] / "src" / "samples"
    if not samples_root.is_dir():
        return False
    return any(child.is_dir() and child.name != "__pycache__" for child in samples_root.iterdir())


def _spec_name(spec: Any) -> str | None:
    if isinstance(spec, dict):
        return spec.get("name")
    return getattr(spec, "name", None)


def register_host_canary_tools(host_cls: type) -> None:
    """Attach canary tools to ``host_cls`` (idempotent)."""
    if getattr(host_cls, _FLAG, False):
        return
    canary_tools.register(host_cls)
    setattr(host_cls, _FLAG, True)


def unregister_host_canary_tools(host_cls: type) -> None:
    """Remove canary tools without wiping domain tools registered while canaries were on."""
    if not getattr(host_cls, _FLAG, False):
        return
    specs = getattr(host_cls, "_cls_specs", None)
    if specs is not None:
        specs[:] = [spec for spec in specs if _spec_name(spec) not in _CANARY_NAMES]
    for name in _CANARY_ATTRS:
        if name in host_cls.__dict__:
            delattr(host_cls, name)
    setattr(host_cls, _FLAG, False)


def clear_host_caches() -> None:
    from src.config import get_settings
    from src.host.facade import get_host_bfa
    from src.host.factory import get_host_blueprint

    get_settings.cache_clear()
    get_host_bfa.cache_clear()
    get_host_blueprint.cache_clear()


@contextmanager
def host_canaries_installed() -> Iterator[None]:
    from src.host.facade import HostSampleBFA

    register_host_canary_tools(HostSampleBFA)
    clear_host_caches()
    try:
        yield
    finally:
        unregister_host_canary_tools(HostSampleBFA)
        clear_host_caches()
