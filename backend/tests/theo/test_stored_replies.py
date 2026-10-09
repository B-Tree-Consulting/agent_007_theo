"""StoredReply for market-data reads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.theo.clients.market_data import MarketDataClient


def test_yahoo_cooldown_returns_the_stored_chart_and_a_transport_error_does_not_set_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        theo_finnhub_api_key = None
        theo_tiingo_api_key = None
        theo_alpha_vantage_api_key = None
        theo_fred_api_key = None
        theo_sec_user_agent = None

    monkeypatch.setattr("src.theo.clients.market_data.get_settings", lambda: _Settings())
    clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr("src.theo.stores.replies._now", lambda: clock["now"])
    calls = {"n": 0}
    mode = {"kind": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if mode["kind"] == "down":
            raise httpx.ConnectError("down", request=request)
        if mode["kind"] == "limited":
            return httpx.Response(429, headers={"Retry-After": "30"}, json={"message": "later"})
        return httpx.Response(
            200,
            json={"chart": {"result": [{"meta": {"regularMarketPrice": 10}}]}},
        )

    client = MarketDataClient(transport=httpx.MockTransport(handler))
    first = asyncio.run(client.research("AAPL_US_EQ"))
    assert first.quote is not None
    assert first.quote.stored is False
    assert first.quote.data["last_price"] == "10"
    assert calls["n"] >= 1
    after_success = calls["n"]

    mode["kind"] = "limited"
    limited = asyncio.run(client.research("AAPL_US_EQ"))
    assert limited.quote is not None
    assert limited.quote.stored is True
    assert limited.quote.fetched_at is not None
    during = calls["n"]
    again = asyncio.run(client.research("AAPL_US_EQ"))
    assert again.quote is not None and again.quote.stored is True
    assert calls["n"] == during

    clock["now"] += timedelta(seconds=31)
    mode["kind"] = "down"
    stale = asyncio.run(client.research("AAPL_US_EQ"))
    assert stale.quote is not None
    assert stale.quote.stored is True
    assert calls["n"] > during
    assert after_success >= 1
