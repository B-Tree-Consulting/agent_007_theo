"""Application settings loaded from environment (.env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Self
from uuid import UUID

from pydantic import AliasChoices, Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MAX_IDP_AUDIENCE_LEN = 384


def parse_entra_api_guid_from_audience_string(raw: str) -> UUID | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return UUID(s)
    except ValueError:
        pass
    lower = s.lower()
    if lower.startswith("api://"):
        segment = s[6:].split("/")[0].strip()
        try:
            return UUID(segment)
        except ValueError:
            return None
    return None


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str

    auth_enabled: bool = True
    auth_test_mode: bool = False
    auth_provider: str = "azure"

    idp_issuer: str | None = None
    idp_audience: str | None = None
    idp_jwks_uri: str | None = None

    aydeo_entra_app_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP_ID", "AYDEO_ENTRA_APP_ID", "ENTRA_CLIENT_ID"),
    )

    jwks_cache_ttl_seconds: int = 600
    jwks_fetch_timeout_seconds: float = 3.0
    jwt_leeway_seconds: int = 120

    aydeo_um_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AYDEO_UM_BASE_URL", "AYDEO_API_BASE_URL"),
    )
    um_http_timeout_seconds: float = 5.0

    aydeo_chat_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AYDEO_CHAT_BASE_URL"),
    )
    chat_http_timeout_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices("CHAT_HTTP_TIMEOUT_SECONDS"),
    )

    aydeo_config_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AYDEO_CONFIG_BASE_URL"),
    )

    dris_capability_jwks_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DRIS_CAPABILITY_JWKS_URI"),
    )
    dris_capability_issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DRIS_CAPABILITY_ISSUER"),
    )

    aydeo_platform_approval_proof_jwks_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL",
            "APPROVAL_PROOF_JWKS_URL",
        ),
    )
    aydeo_platform_approval_proof_issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER",
            "APPROVAL_PROOF_ISSUER",
        ),
    )

    aydeo_chat_internal_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AYDEO_CHAT_INTERNAL_TOKEN",
            "CHAT_INTERNAL_TOKEN",
            "OUTBOX_INTERNAL_SERVICE_TOKEN",
        ),
    )

    aydeo_cms_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AYDEO_CMS_BASE_URL"),
    )
    aydeo_platform_internal_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN"),
    )

    aydeo_audit_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AYDEO_AUDIT_URL"),
    )
    aydeo_audit_spool_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AYDEO_AUDIT_SPOOL_PATH"),
    )
    outbox_internal_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OUTBOX_INTERNAL_SERVICE_TOKEN"),
    )

    log_level: str = Field(
        default="info",
        validation_alias=AliasChoices("LOG_LEVEL"),
    )
    bfa_service_slug: str = Field(
        default="agent-007-theo",
        validation_alias=AliasChoices("BFA_SERVICE_SLUG"),
    )
    service_version: str = Field(
        default="0.1.0",
        validation_alias=AliasChoices("SERVICE_VERSION"),
    )
    bfa_test_de_id: str = Field(
        default="00000000-0000-4000-8000-0000000000de",
        validation_alias=AliasChoices("BFA_TEST_DE_ID"),
        description="Mock DE subject for AUTH_TEST_MODE / Postman only — not used as runtime identity in production.",
    )
    bfa_confirm_test_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("BFA_CONFIRM_TEST_MODE"),
    )
    bfa_invoke_diagnostic_mode: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("BFA_INVOKE_DIAGNOSTIC_MODE"),
    )

    _resolved_aydeo_entra_api_client_id: UUID | None = PrivateAttr(default=None)

    @property
    def invoke_diagnostic_mode(self) -> bool:
        if self.bfa_invoke_diagnostic_mode is not None:
            return self.bfa_invoke_diagnostic_mode
        return self.auth_test_mode

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v: object) -> str:
        allowed = frozenset({"critical", "error", "warning", "info", "debug", "trace"})
        if v is None:
            return "info"
        if not isinstance(v, str):
            raise ValueError("LOG_LEVEL must be a string")
        s = v.strip().lower()
        if not s:
            return "info"
        if s == "warn":
            s = "warning"
        if s not in allowed:
            raise ValueError(
                f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))} (got {v!r})"
            )
        return s

    @field_validator("idp_audience", mode="before")
    @classmethod
    def _validate_idp_audience_len(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        s = v.strip()
        if not s:
            return None
        if len(s) > _MAX_IDP_AUDIENCE_LEN:
            raise ValueError(f"IDP_AUDIENCE exceeds maximum length ({_MAX_IDP_AUDIENCE_LEN} characters)")
        return s

    @field_validator("aydeo_entra_app_id", mode="before")
    @classmethod
    def _normalize_aydeo_entra_app_id(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        s = v.strip()
        if not s:
            return None
        if s.startswith("<") and s.endswith(">"):
            return None
        return s

    @field_validator(
        "aydeo_audit_spool_path",
        "outbox_internal_service_token",
        "aydeo_platform_internal_service_token",
        mode="before",
    )
    @classmethod
    def _normalize_optional_nonempty_strings(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        s = v.strip()
        return s or None

    @field_validator(
        "aydeo_um_base_url",
        "aydeo_audit_url",
        "aydeo_chat_base_url",
        "aydeo_config_base_url",
        "aydeo_cms_base_url",
        mode="before",
    )
    @classmethod
    def _normalize_optional_http_base_urls(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        s = v.strip()
        if not s:
            return None
        lower = s.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            return f"http://{s}"
        return s

    @model_validator(mode="after")
    def _resolve_entra_api_app(self) -> Self:
        app_raw = self.aydeo_entra_app_id
        uuid_from_app: UUID | None = None
        if app_raw:
            try:
                uuid_from_app = UUID(app_raw)
            except ValueError as exc:
                raise ValueError(
                    "APP_ID must be a Microsoft Entra application (client) id UUID",
                ) from exc

        uuid_from_audience = parse_entra_api_guid_from_audience_string(self.idp_audience or "")
        if uuid_from_app is not None and uuid_from_audience is not None and uuid_from_app != uuid_from_audience:
            raise ValueError("Conflicting AyDEO Entra API application ids between APP_ID and IDP_AUDIENCE")

        self._resolved_aydeo_entra_api_client_id = uuid_from_app or uuid_from_audience
        return self

    @model_validator(mode="after")
    def _prod_diagnostic_guard(self) -> Self:
        if not self.auth_test_mode and self.invoke_diagnostic_mode:
            raise ValueError("BFA invoke diagnostic mode requires AUTH_TEST_MODE=true")
        return self

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgresql+psycopg://"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url.removeprefix("postgresql://")
        raise ValueError("DATABASE_URL must start with postgresql:// or postgresql+psycopg://")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
