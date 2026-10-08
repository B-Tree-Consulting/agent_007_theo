"""Isolation guards: production assembly must not reference removed canary package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bfa.aydeo_host.platform.factory import build_aydeo_host
from src.host import factory as host_factory
from src.host.factory import warm_host_on_startup


def _source_paths() -> list[Path]:
    backend = Path(__file__).resolve().parent.parent.parent
    return [
        backend / "src" / "host" / "factory.py",
        backend / "src" / "host" / "api.py",
        backend / "src" / "main.py",
    ]


def test_default_modules_do_not_reference_canary_package() -> None:
    for path in _source_paths():
        source = path.read_text(encoding="utf-8")
        assert "build_canary_aydeo_host" not in source, path.name
        assert "host.canary" not in source, path.name
        assert "canary_host_tools" not in source, path.name
        assert "canary_query_bounded" not in source, path.name
        assert "tests.fixtures.case_policy_parity" not in source, path.name


@pytest.mark.no_host_canaries
def test_warm_host_on_startup_uses_get_host_blueprint_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _track_get_host_blueprint():
        calls.append("get_host_blueprint")

    filled = type("FilledFacade", (), {"tools": staticmethod(lambda: {"canary_query_bounded": object()})})()
    monkeypatch.setattr(host_factory, "get_host_blueprint", _track_get_host_blueprint)
    monkeypatch.setattr(host_factory, "get_host_bfa", lambda: filled)
    warm_host_on_startup()
    assert calls == ["get_host_blueprint"]


@pytest.mark.no_host_canaries
def test_warm_host_on_startup_raises_when_facade_has_no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = type("EmptyFacade", (), {"tools": staticmethod(lambda: ())})()
    monkeypatch.setattr(host_factory, "get_host_blueprint", lambda: object())
    monkeypatch.setattr(host_factory, "get_host_bfa", lambda: empty)
    with pytest.raises(RuntimeError, match="no tools after sample bootstrap"):
        warm_host_on_startup()


def test_build_aydeo_host_rejects_policy_overrides() -> None:
    from bfa import BFA, CallContext, Resolver
    from bfa.aydeo_host import CaseScopePolicy, HoldPolicy, HostConfig
    from bfa.aydeo_host.platform.factory import CatalogScopeHelpers

    from tests.fixtures.case_policy_parity.scenario_case_state_adapter import ScenarioCaseStateAdapter

    class _R(Resolver):
        def get(self, key: str):
            return None

        def scoped(self, ctx: CallContext):
            class _S:
                def get(self, key: str):
                    return None

            return _S()

    bfa = BFA(resolver=_R(), token_introspector=object(), employee_id="x")  # type: ignore[arg-type]
    settings = __import__(
        "tests.host.case_policy_harness", fromlist=["dummy_platform_settings"]
    ).dummy_platform_settings()
    catalog = CatalogScopeHelpers(is_scoped_tool=lambda n: True, resolve_case_scope=lambda n: "active_open_case")
    adapter = ScenarioCaseStateAdapter()

    with pytest.raises(ValueError, match="case_scope_policy"):
        build_aydeo_host(
            bfa=bfa,
            settings=settings,
            config=HostConfig(service_name="x", service_version=settings.service_version),
            case_state_adapter=adapter,
            catalog_scope=catalog,
            case_scope_policy=CaseScopePolicy(catalog_scope=catalog),
        )

    with pytest.raises(ValueError, match="hold_policy"):
        build_aydeo_host(
            bfa=bfa,
            settings=settings,
            config=HostConfig(service_name="x", service_version=settings.service_version),
            case_state_adapter=adapter,
            catalog_scope=catalog,
            hold_policy=HoldPolicy(catalog_scope=catalog),
        )

    from bfa.aydeo_host import CaseWorkAuthorityPolicy

    with pytest.raises(ValueError, match="case_role_policy"):
        build_aydeo_host(
            bfa=bfa,
            settings=settings,
            config=HostConfig(service_name="x", service_version=settings.service_version),
            case_state_adapter=adapter,
            catalog_scope=catalog,
            case_role_policy=CaseWorkAuthorityPolicy(catalog_scope=catalog),
        )

    with pytest.raises(ValueError, match="case_work_authority_policy"):
        build_aydeo_host(
            bfa=bfa,
            settings=settings,
            config=HostConfig(service_name="x", service_version=settings.service_version),
            case_state_adapter=adapter,
            catalog_scope=catalog,
            case_work_authority_policy=CaseWorkAuthorityPolicy(catalog_scope=catalog),
        )
