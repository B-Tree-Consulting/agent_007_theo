"""Mock IdP utilities for AUTH_TEST_MODE."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

TEST_SECRET_KEY = "test-secret-key-do-not-use-in-production"
ALGORITHM = "HS256"

STANDARD_ROLES = {
    "AyDEO-DE": {
        "description": "Digital Employee - standard role for all DEs",
        "scopes": ["cases:read", "cases:write"],
    },
    "DRIS-Admin": {
        "description": "System administrator - full access",
        "scopes": ["*"],
    },
    "AyDEO-Config-Admin": {
        "description": "AyDEO Config administrator",
        "scopes": ["*"],
    },
    "DRIS-Organization-Admin": {
        "description": "Organization admin",
        "scopes": ["teams:read", "teams:write"],
    },
    "DRIS-Team-Admin": {
        "description": "Team admin",
        "scopes": ["teams:read", "teams:write"],
    },
    "DRIS-Digital-Employee-Admin": {
        "description": "Digital Employee admin",
        "scopes": ["employees:read", "employees:write"],
    },
}


class MockIdP:
    @classmethod
    def create_token(
        cls,
        subject: str,
        roles: list[str] | None = None,
        scopes: list[str] | None = None,
        **extra_claims: object,
    ) -> str:
        payload = {
            "sub": subject,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "roles": roles or [],
            "scope": " ".join(scopes or []),
            **extra_claims,
        }
        return jwt.encode(payload, TEST_SECRET_KEY, algorithm=ALGORITHM)

    @classmethod
    def decode_without_verification(cls, token: str) -> dict:
        return jwt.decode(token, options={"verify_signature": False})


def create_de_token(employee_id: str) -> str:
    return MockIdP.create_token(
        subject=employee_id,
        roles=["AyDEO-DE"],
        scopes=STANDARD_ROLES["AyDEO-DE"]["scopes"],
    )


def create_config_admin_token(user_id: str = "config-admin@test.com") -> str:
    return MockIdP.create_token(
        subject=user_id,
        roles=["AyDEO-Config-Admin"],
        scopes=STANDARD_ROLES["AyDEO-Config-Admin"]["scopes"],
    )
