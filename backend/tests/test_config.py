"""Settings validation tests."""

import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings, parse_entra_api_guid_from_audience_string

_GUID = "00000000-0000-4000-8000-000000000099"


def test_aydeo_entra_app_id_template_placeholder_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("APP_ID", "<application-client-id-guid>")
    settings = Settings()
    assert settings.aydeo_entra_app_id is None
    assert settings._resolved_aydeo_entra_api_client_id is None  # noqa: SLF001


def test_parse_entra_api_guid_from_audience_string() -> None:
    guid = "00000000-0000-4000-8000-000000000099"
    assert parse_entra_api_guid_from_audience_string(guid) is not None
    assert parse_entra_api_guid_from_audience_string(f"api://{guid}/scope") is not None
    assert parse_entra_api_guid_from_audience_string("not-a-guid") is None
    assert parse_entra_api_guid_from_audience_string("") is None
    assert parse_entra_api_guid_from_audience_string("api://not-a-guid/scope") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("https://api.example", "https://api.example"),
        ("api.example", "http://api.example"),
    ],
)
def test_normalize_optional_http_base_urls(raw: str | None, expected: str | None) -> None:
    settings = Settings(
        database_url="postgresql://u:p@localhost:5432/db",
        aydeo_um_base_url=raw,
    )
    assert settings.aydeo_um_base_url == expected


def test_sqlalchemy_url_normalizes_driver() -> None:
    settings = Settings(database_url="postgresql://u:p@localhost:5432/db")
    assert settings.sqlalchemy_url.startswith("postgresql+psycopg://")

    native = Settings(database_url="postgresql+psycopg://u:p@localhost:5432/db")
    assert native.sqlalchemy_url == "postgresql+psycopg://u:p@localhost:5432/db"


def test_sqlalchemy_url_rejects_unknown_scheme() -> None:
    settings = Settings(database_url="mysql://u:p@localhost/db")
    with pytest.raises(ValueError, match="DATABASE_URL must start with postgresql"):
        _ = settings.sqlalchemy_url


def test_resolve_entra_api_client_id_from_audience_only() -> None:
    settings = Settings(
        database_url="postgresql://u:p@localhost:5432/db",
        idp_audience=_GUID,
    )
    assert settings._resolved_aydeo_entra_api_client_id is not None  # noqa: SLF001


def test_invalid_app_id_raises() -> None:
    with pytest.raises(ValidationError, match="APP_ID must be a Microsoft Entra"):
        Settings(database_url="postgresql://u:p@localhost:5432/db", aydeo_entra_app_id="not-a-uuid")


def test_conflicting_app_id_and_audience_raises() -> None:
    other = "00000000-0000-4000-8000-000000000001"
    with pytest.raises(ValidationError, match="Conflicting AyDEO Entra API application ids"):
        Settings(
            database_url="postgresql://u:p@localhost:5432/db",
            aydeo_entra_app_id=_GUID,
            idp_audience=other,
        )


def test_idp_audience_max_length_enforced() -> None:
    with pytest.raises(ValidationError, match="IDP_AUDIENCE exceeds maximum length"):
        Settings(
            database_url="postgresql://u:p@localhost:5432/db",
            idp_audience="x" * 385,
        )


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("auth_test_mode", "invoke_override", "expected", "raises"),
    [
        (False, None, False, False),
        (True, None, True, False),
        (True, False, False, False),
        (True, True, True, False),
    ],
)
def test_invoke_diagnostic_mode_truth_table_ok(
    monkeypatch: pytest.MonkeyPatch,
    auth_test_mode: bool,
    invoke_override: bool | None,
    expected: bool,
    raises: bool,
) -> None:
    del raises
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("AUTH_TEST_MODE", "true" if auth_test_mode else "false")
    if invoke_override is None:
        monkeypatch.delenv("BFA_INVOKE_DIAGNOSTIC_MODE", raising=False)
    else:
        monkeypatch.setenv("BFA_INVOKE_DIAGNOSTIC_MODE", "true" if invoke_override else "false")
    settings = Settings()
    assert settings.invoke_diagnostic_mode is expected


def test_invoke_diagnostic_mode_prod_guard_rejects() -> None:
    with pytest.raises(ValidationError, match="requires AUTH_TEST_MODE=true"):
        Settings(
            database_url="postgresql://u:p@localhost:5432/db",
            auth_test_mode=False,
            bfa_invoke_diagnostic_mode=True,
        )


def test_bfa_test_de_id_from_primary_env() -> None:
    settings = Settings(
        database_url="postgresql://u:p@localhost:5432/db",
        bfa_test_de_id="00000000-0000-4000-8000-0000000000ab",
    )
    assert settings.bfa_test_de_id == "00000000-0000-4000-8000-0000000000ab"


def test_aydeo_audit_spool_path_blank_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AYDEO_AUDIT_SPOOL_PATH", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
        aydeo_audit_spool_path="   ",
    )
    assert settings.aydeo_audit_spool_path is None


def test_outbox_internal_service_token_blank_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Shared alias with aydeo_chat_internal_token; isolate from repo .env / os.environ.
    monkeypatch.delenv("OUTBOX_INTERNAL_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("AYDEO_INTERNAL_SERVICE_TOKEN", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
        outbox_internal_service_token="  ",
    )
    assert settings.outbox_internal_service_token is None


def test_platform_internal_token_blank_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
        aydeo_platform_internal_service_token="  ",
    )
    assert settings.aydeo_platform_internal_service_token is None


def test_platform_internal_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN", "platform-token")
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
    )
    assert settings.aydeo_platform_internal_service_token == "platform-token"


def test_platform_internal_token_ignores_outbox_and_internal_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("AYDEO_INTERNAL_SERVICE_TOKEN", "internal-alias")
    monkeypatch.setenv("OUTBOX_INTERNAL_SERVICE_TOKEN", "outbox-alias")
    settings = Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost:5432/db",
    )
    assert settings.aydeo_platform_internal_service_token is None


def test_orchestration_url_placeholders_accepted() -> None:
    settings = Settings(
        database_url="postgresql://u:p@localhost:5432/db",
        aydeo_chat_base_url="http://chat.local",
        aydeo_config_base_url="http://config.local",
        dris_capability_jwks_uri="https://dris.local/jwks.json",
        dris_capability_issuer="https://dris.local",
        aydeo_cms_base_url="http://cms.local",
    )
    assert settings.aydeo_chat_base_url == "http://chat.local"
    assert settings.aydeo_config_base_url == "http://config.local"
    assert settings.dris_capability_jwks_uri == "https://dris.local/jwks.json"


def test_field_validators_handle_none_and_non_string_inputs() -> None:
    assert Settings._validate_idp_audience_len(None) is None
    assert Settings._validate_idp_audience_len(123) == 123
    assert Settings._validate_idp_audience_len("   ") is None

    assert Settings._normalize_aydeo_entra_app_id(None) is None
    assert Settings._normalize_aydeo_entra_app_id(456) == 456
    assert Settings._normalize_aydeo_entra_app_id("   ") is None

    assert Settings._normalize_optional_http_base_urls(None) is None
    assert Settings._normalize_optional_http_base_urls(789) == 789


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "info"),
        ("", "info"),
        ("  ", "info"),
        ("warn", "warning"),
        ("WARNING", "warning"),
        ("DEBUG", "debug"),
        ("trace", "trace"),
        ("info", "info"),
    ],
)
def test_log_level_normalization(raw: str | None, expected: str) -> None:
    settings = Settings(
        database_url="postgresql://u:p@localhost:5432/db",
        log_level=raw,  # type: ignore[arg-type]
    )
    assert settings.log_level == expected


def test_log_level_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql://u:p@localhost:5432/db",
            log_level="verbose",
        )


def test_log_level_rejects_non_string() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql://u:p@localhost:5432/db",
            log_level=123,  # type: ignore[arg-type]
        )