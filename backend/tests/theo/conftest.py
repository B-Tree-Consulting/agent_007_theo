"""Theo domain tests share broker/market doubles."""

from __future__ import annotations

import pytest

from tests.host.conftest import (  # noqa: F401
    _host_canaries_when_sample_absent,
    _mock_open_case_cms,
    _patch_test_platform_adapters,
    _stub_case_comment_posts,
    case_identity_overlay,
    client,
    de_id,
    recorded_case_comments,
    sample_capability_token,
)
from tests.theo.fakes import FakeMarket, FakeT212, fake_fx


@pytest.fixture
def fake_t212() -> FakeT212:
    return FakeT212()


@pytest.fixture
def fake_market() -> FakeMarket:
    return FakeMarket()


@pytest.fixture(autouse=True)
def _patch_theo_clients(
    monkeypatch: pytest.MonkeyPatch,
    fake_t212: FakeT212,
    fake_market: FakeMarket,
) -> None:
    monkeypatch.setenv("THEO_WHITELIST", "AAPL_US_EQ,MSFT_US_EQ")
    monkeypatch.setenv("THEO_WHITELIST_PATH", "")
    monkeypatch.setenv("T212_API_KEY", "demo-key")
    monkeypatch.setenv("T212_API_SECRET", "demo-secret")
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("src.theo.clients.t212.get_t212_client", lambda: fake_t212)
    monkeypatch.setattr("src.theo.snapshot.get_t212_client", lambda: fake_t212)
    monkeypatch.setattr("src.theo.actions.get_t212_client", lambda: fake_t212)
    monkeypatch.setattr("src.theo.snapshot.get_market_data_client", lambda: fake_market)
    monkeypatch.setattr("src.theo.queries.get_market_data_client", lambda: fake_market)
    monkeypatch.setattr("src.theo.clients.market_data.get_market_data_client", lambda: fake_market)

    async def _fx(*_args, **_kwargs):
        return fake_fx()

    monkeypatch.setattr("src.theo.snapshot.load_fixing", _fx)
    monkeypatch.setattr("src.theo.clients.cnb.load_fixing", _fx)
    yield
    get_settings.cache_clear()
