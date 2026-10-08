"""Unit tests for host-neutral HTTP helpers."""

from __future__ import annotations

import pytest

from tests.host.http_helpers import assert_deferred


def test_assert_deferred_needs_confirmation() -> None:
    body = {
        "status": "failed",
        "outputs": {"plan_token": "tok-abc"},
        "assertions": [{"id": "needs-confirmation"}],
    }
    assert assert_deferred(body, "needs-confirmation") == "tok-abc"


def test_assert_deferred_needs_superior_defer() -> None:
    body = {
        "status": "failed",
        "outputs": {"plan_token": "tok-high"},
        "assertions": [{"id": "needs-superior-defer"}],
    }
    assert assert_deferred(body, "needs-superior-defer") == "tok-high"


def test_assert_deferred_missing_assertion_raises() -> None:
    body = {
        "status": "failed",
        "outputs": {"plan_token": "tok"},
        "assertions": [{"id": "needs-confirmation"}],
    }
    with pytest.raises(AssertionError, match="needs-superior-defer"):
        assert_deferred(body, "needs-superior-defer")
