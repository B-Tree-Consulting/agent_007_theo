"""Entra audience alignment with AyDEO platform (discover catalog probe)."""

from __future__ import annotations

from uuid import UUID

import pytest

from src.config import Settings
from src.host.factory import _entra_audiences_for_platform


def test_entra_audiences_include_access_as_user_from_app_id(monkeypatch) -> None:
    guid = "a6dc5888-6677-48b4-a11f-d4065e8af80a"
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        aydeo_entra_app_id=guid,
        idp_audience=f"api://{guid}",
    )
    audiences = _entra_audiences_for_platform(settings)
    assert f"api://{guid}/access_as_user" in audiences
    assert f"api://{guid}/.default" in audiences
    assert guid in audiences


def test_entra_audiences_derive_from_idp_audience_only(monkeypatch) -> None:
    guid = UUID("00000000-0000-4000-8000-000000000099")
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        idp_audience=f"api://{guid}/custom-scope",
    )
    audiences = _entra_audiences_for_platform(settings)
    assert "api://00000000-0000-4000-8000-000000000099/access_as_user" in audiences
    assert "api://00000000-0000-4000-8000-000000000099/custom-scope" in audiences


def test_entra_audiences_non_guid_idp_audience_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ID", "")
    monkeypatch.setenv("AYDEO_ENTRA_APP_ID", "")
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        idp_audience="legacy-custom-audience",
    )
    audiences = _entra_audiences_for_platform(settings)
    assert audiences == ["legacy-custom-audience"]


def test_entra_audiences_dedupe_lowercase_app_id_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IDP_AUDIENCE", raising=False)
    guid = "a6dc5888-6677-48b4-a11f-d4065e8af80a"
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        aydeo_entra_app_id=guid,
    )
    audiences = _entra_audiences_for_platform(settings)
    assert audiences.count(guid) == 1
    assert len(audiences) == len(set(audiences))


def test_entra_audiences_dedupe_guid_derived_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ID", raising=False)
    guid = "a6dc5888-6677-48b4-a11f-d4065e8af80a"
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        idp_audience=f"api://{guid}/access_as_user,api://{guid}",
    )
    audiences = _entra_audiences_for_platform(settings)
    assert audiences.count(f"api://{guid}/access_as_user") == 1


def test_entra_audiences_skip_resolved_guid_already_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.host import factory as host_factory

    guid = "a6dc5888-6677-48b4-a11f-d4065e8af80a"
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        aydeo_entra_app_id=guid,
    )
    real = host_factory._finite_derived_api_audiences_from_guid
    derived = real(guid)

    def _duplicate_then_real(value: str) -> list[str]:
        first = real(value)
        return [first[0], *first] if first else []

    monkeypatch.setattr(host_factory, "_finite_derived_api_audiences_from_guid", _duplicate_then_real)
    audiences = host_factory._entra_audiences_for_platform(settings)
    assert audiences[: len(derived)] == derived


def test_entra_audiences_append_guid_derived_when_resolved_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ID", "")
    monkeypatch.setenv("AYDEO_ENTRA_APP_ID", "")
    guid = "a6dc5888-6677-48b4-a11f-d4065e8af80a"
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        idp_audience=f"legacy-custom-audience,api://{guid}",
    )
    assert settings._resolved_aydeo_entra_api_client_id is None
    audiences = _entra_audiences_for_platform(settings)
    assert audiences[0] == "legacy-custom-audience"
    assert f"api://{guid}/access_as_user" in audiences
