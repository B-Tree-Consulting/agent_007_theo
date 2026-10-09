"""Cover the Trading 212 and market-data client branches the backoff tests leave out."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from src.theo.clients.market_data import (
    MarketDataClient,
    get_market_data_client,
    reset_market_data_client,
)
from src.theo.clients.rate_limit import positive_header_wait
from src.theo.clients.t212 import (
    T212Client,
    _stamp_rows,
    current_t212_environment,
    get_t212_client,
    reset_t212_client,
)
from src.theo.errors import TheoError
from src.theo.schemas import OrderInput, OrderType, Side, TimeValidity


def _t212(handler) -> T212Client:
    return T212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="k",
        api_secret="s",
        transport=httpx.MockTransport(handler),
    )


def _order(**overrides) -> OrderInput:
    fields = {
        "ticker": "AAPL_US_EQ",
        "side": Side.sell,
        "quantity": Decimal("2"),
        "order_type": OrderType.market,
        "extended_hours": True,
    }
    fields.update(overrides)
    return OrderInput(**fields)


def test_live_client_environment_and_close() -> None:
    client = T212Client(
        base_url="https://live.trading212.com/api/v0/",
        api_key="k",
        api_secret="s",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    assert client.environment == "live"
    assert client.base_url == "https://live.trading212.com/api/v0"
    asyncio.run(client.aclose())


def test_positions_accept_a_list_or_an_items_page() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json=[
                    {
                        "ticker": "AAPL_US_EQ",
                        "quantity": "2",
                        "averagePrice": "10",
                        "currentPrice": "12",
                        "ppl": "4",
                        "instrument": {"currency": "USD"},
                    }
                ],
            )
        return httpx.Response(200, json={"items": [{"ticker": "MSFT_US_EQ"}]})

    client = _t212(handler)
    first = asyncio.run(client.positions())
    second = asyncio.run(client.positions())
    assert first[0]["currency"] == "USD"
    assert first[0]["quantity"] == Decimal("2")
    assert second[0]["average_price"] is None
    assert second[0]["quantity"] == Decimal("0")


def test_open_orders_follow_the_next_page_and_history_can_be_a_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url)
        if "cursor=2" in path:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "orderId": "2",
                            "orderType": "STOPLIMIT",
                            "quantity": "1",
                            "createdAt": "2026-01-01T00:00:00Z",
                            "timeValidity": "NOPE",
                        }
                    ],
                    "nextPagePath": None,
                },
            )
        if path.endswith("/equity/orders"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "1",
                            "ticker": "AAPL_US_EQ",
                            "type": "LIMIT",
                            "quantity": "-3",
                            "creationTime": "not-a-date",
                            "timeValidity": "DAY",
                            "limitPrice": "10",
                            "stopPrice": "9",
                            "status": "NEW",
                        }
                    ],
                    "nextPagePath": "/equity/orders?cursor=2",
                },
            )
        return httpx.Response(
            200,
            json=[{"type": "STOP", "quantity": 0, "creationTime": "2026-01-02T00:00:00+00:00"}],
        )

    client = _t212(handler)
    orders = asyncio.run(client.open_orders())
    assert [row["t212_order_id"] for row in orders] == ["1", "2"]
    assert orders[0]["side"] == Side.sell
    assert orders[0]["order_type"] == OrderType.limit
    assert orders[0]["time_validity"] == TimeValidity.DAY
    assert orders[0]["created_at"].tzinfo is not None
    assert orders[1]["order_type"] == OrderType.stop_limit
    assert orders[1]["time_validity"] is None
    history = asyncio.run(client.historical_orders())
    assert history[0]["order_type"] == OrderType.stop
    assert history[0]["side"] == Side.buy
    assert history[0]["t212_order_id"] == ""


def test_historical_orders_and_get_order_swallow_a_broker_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/99"):
            return httpx.Response(200, json={"id": "99", "type": "MARKET", "quantity": "1"})
        return httpx.Response(500, text="down")

    client = _t212(handler)
    assert asyncio.run(client.historical_orders()) == []
    assert asyncio.run(client.get_order("1")) is None
    found = asyncio.run(client.get_order("99"))
    assert found is not None
    assert found["t212_order_id"] == "99"


def test_cancel_and_each_place_shape() -> None:
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            body = httpx.Response(200, content=request.content).json()
        seen.append((request.method, request.url.path, body))
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        if request.url.path.endswith("/stop_limit"):
            return httpx.Response(200, json={"orderId": "sl"})
        if request.url.path.endswith("/stop"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/limit"):
            return httpx.Response(200, json={"id": "lim"})
        return httpx.Response(400, text="   ")

    client = _t212(handler)
    limit_id = asyncio.run(
        client.place_order(
            _order(
                order_type=OrderType.limit,
                limit_price=Decimal("10"),
                time_validity=TimeValidity.GOOD_TILL_CANCEL,
            )
        )
    )
    stop_limit_id = asyncio.run(
        client.place_order(
            _order(
                order_type=OrderType.stop_limit,
                limit_price=Decimal("11"),
                stop_price=Decimal("12"),
                time_validity=TimeValidity.DAY,
            )
        )
    )
    with pytest.raises(TheoError) as missing:
        asyncio.run(client.place_order(_order(order_type=OrderType.stop, stop_price=Decimal("8"))))
    with pytest.raises(TheoError) as empty:
        asyncio.run(client.place_order(_order()))
    asyncio.run(client.cancel_order("lim"))
    assert limit_id == "lim"
    assert stop_limit_id == "sl"
    assert missing.value.message == "Broker accepted the order but returned no id"
    assert empty.value.message == "HTTP 400"
    methods = [item[0] for item in seen]
    assert "DELETE" in methods
    limit_body = next(body for method, path, body in seen if path.endswith("/limit"))
    assert limit_body["extendedHours"] is True
    assert limit_body["limitPrice"] == 10.0
    assert limit_body["timeValidity"] == "GOOD_TILL_CANCEL"
    assert limit_body["quantity"] < 0


def test_metadata_transport_and_server_errors_keep_a_stored_list(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": datetime(2026, 2, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr("src.theo.stores.replies._now", lambda: clock["now"])
    mode = {"kind": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        if mode["kind"] == "down":
            raise httpx.ConnectError("down", request=request)
        if mode["kind"] == "bad":
            return httpx.Response(500, json={"error": "later"})
        if mode["kind"] == "text":
            return httpx.Response(502, text="not-json")
        if mode["kind"] == "blank":
            return httpx.Response(400, json={})
        return httpx.Response(
            200,
            json=[
                {"ticker": "AAPL_US_EQ", "currency": "USD", "shortName": "Apple", "minTradeQuantity": "0.5"},
                {"currencyCode": "EUR", "quantityStep": "1"},
                {"minTradeQuantity": "-1"},
                {"quantityStep": "0"},
            ],
        )

    client = _t212(handler)
    rows = asyncio.run(client.metadata_instruments())
    assert rows[0]["name"] == "Apple"
    assert rows[0]["quantity_step"] == Decimal("0.5")
    assert rows[1]["quantity_step"] == Decimal("1")
    assert rows[2]["quantity_step"] == Decimal("0.0001")
    assert rows[3]["working_schedule_id"] is None
    mode["kind"] = "down"
    stored = asyncio.run(client.metadata_instruments())
    assert stored[0]["stored"] is True
    mode["kind"] = "bad"
    clock["now"] += timedelta(seconds=5)
    still = asyncio.run(client.metadata_instruments())
    assert still[0]["ticker"] == "AAPL_US_EQ"
    assert still[0]["stored"] is True

    fresh = _t212(handler)
    mode["kind"] = "bad"
    with pytest.raises(TheoError) as broker_error:
        asyncio.run(fresh.metadata_exchanges())
    assert broker_error.value.message == "later"
    mode["kind"] = "text"
    with pytest.raises(TheoError) as text_error:
        asyncio.run(fresh.metadata_exchanges())
    assert text_error.value.message == "HTTP 502"
    mode["kind"] = "blank"
    with pytest.raises(TheoError) as blank:
        asyncio.run(fresh.metadata_exchanges())
    assert blank.value.message == "Bad Request"
    mode["kind"] = "down"
    with pytest.raises(httpx.ConnectError):
        asyncio.run(fresh.metadata_exchanges())


def test_metadata_request_is_a_single_send_and_a_bad_row_can_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "exchanges" in request.url.path:
            return httpx.Response(200, json=[{"name": "X", "events": "nope", "workingScheduleId": 4}])
        return httpx.Response(200, json=[{"ticker": "A", "minTradeQuantity": "nope"}])

    client = _t212(handler)
    response = asyncio.run(client._request("GET", "/equity/metadata/instruments?bad-step=1"))
    assert response.status_code == 200
    rows = asyncio.run(client.metadata_exchanges())
    assert rows[0]["events"] == []
    assert rows[0]["working_schedule_id"] == "4"
    with pytest.raises(Exception):
        asyncio.run(client.metadata_instruments())


def test_stamp_rows_skips_or_raises() -> None:
    def boom(_row):
        raise RuntimeError("bad row")

    assert _stamp_rows({"not": "a list"}, boom, None, stored=False, skip_bad_rows=True) == []
    assert _stamp_rows([{"a": 1}, "skip"], boom, None, stored=False, skip_bad_rows=True) == []
    with pytest.raises(RuntimeError):
        _stamp_rows([{"a": 1}], boom, None, stored=False, skip_bad_rows=False)


def test_client_factory_requires_keys_and_reuses_the_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = type(
        "Settings",
        (),
        {"t212_api_key": "", "t212_api_secret": "", "t212_env": "demo", "t212_live_enabled": False},
    )()
    monkeypatch.setattr("src.theo.clients.t212.get_settings", lambda: settings)
    reset_t212_client()
    try:
        with pytest.raises(TheoError):
            get_t212_client()
        settings.t212_api_key = "k"
        settings.t212_api_secret = "s"
        first = get_t212_client()
        assert get_t212_client() is first
        assert current_t212_environment() == "demo"
    finally:
        reset_t212_client()


def test_a_non_object_broker_body_uses_the_status_line() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(400, json=["nope"])

    with pytest.raises(TheoError) as caught:
        asyncio.run(_t212(handler).account_cash())
    assert caught.value.message == "HTTP 400"


def test_garbage_rate_limit_headers_are_not_a_wait() -> None:
    assert positive_header_wait({"x-ratelimit-reset": "soon", "Retry-After": "1"}) == 1.0
    assert positive_header_wait({"Retry-After": "soon"}) is None


class _Keys:
    theo_finnhub_api_key = None
    theo_tiingo_api_key = None
    theo_alpha_vantage_api_key = None
    theo_fred_api_key = None
    theo_sec_user_agent = None


def _keys(**overrides) -> _Keys:
    settings = _Keys()
    for name, value in overrides.items():
        setattr(settings, name, value)
    return settings


def test_last_price_walks_finnhub_yahoo_stooq_then_the_position_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    mode = {"kind": "finnhub"}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "finnhub" in url and mode["kind"] == "finnhub-zero":
            return httpx.Response(200, json={"c": 0})
        if "finnhub" in url and mode["kind"] == "finnhub-bad":
            return httpx.Response(200, json=["nope"])
        if "finnhub" in url and mode["kind"] == "finnhub":
            return httpx.Response(200, json={"c": "12.5"})
        if "yahoo" in url and mode["kind"] == "yahoo-bad":
            return httpx.Response(200, json={"chart": "no"})
        if "yahoo" in url and mode["kind"] in {"stooq", "stooq-nd", "mark", "none"}:
            return httpx.Response(404, json={"message": "missing"})
        if "yahoo" in url and mode["kind"] == "yahoo-close":
            return httpx.Response(
                200,
                json={"chart": {"result": [{"meta": {}, "indicators": {"quote": [{"close": [None, 7.5]}]}}]}},
            )
        if "yahoo" in url:
            return httpx.Response(200, json={"chart": {"result": [{"meta": {"regularMarketPrice": 8}}]}})
        if "stooq" in url and mode["kind"] == "stooq":
            return httpx.Response(200, text="Symbol,Date,Time,Open,High,Low,Close\nA,d,t,1,2,3,4.25\n")
        if "stooq" in url and mode["kind"] == "stooq-nd":
            return httpx.Response(200, text="Symbol,Date,Time,Open,High,Low,Close\nA,d,t,1,2,3,N/D\n")
        if "stooq" in url:
            return httpx.Response(200, text="only-a-header")
        return httpx.Response(500, json={"message": "no"})

    monkeypatch.setattr("src.theo.clients.market_data.get_settings", lambda: _keys(theo_finnhub_api_key="fh"))
    client = MarketDataClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(client.last_price("AAPL_US_EQ")) == (Decimal("12.5"), "finnhub")
    mode["kind"] = "finnhub-zero"
    assert asyncio.run(client.last_price("MSFT_US_EQ")) == (Decimal("8"), "yahoo")
    mode["kind"] = "finnhub-bad"
    assert asyncio.run(client.last_price("IBM_US_EQ")) == (Decimal("8"), "yahoo")
    monkeypatch.setattr("src.theo.clients.market_data.get_settings", lambda: _keys())
    yahoo = MarketDataClient(transport=httpx.MockTransport(handler))
    mode["kind"] = "yahoo-close"
    assert asyncio.run(yahoo.last_price("GOOG_US_EQ")) == (Decimal("7.5"), "yahoo")
    mode["kind"] = "yahoo-bad"
    assert asyncio.run(yahoo.last_price("AMZN_US_EQ", position_mark=Decimal("1"))) == (Decimal("1"), "t212")
    mode["kind"] = "stooq"
    assert asyncio.run(yahoo.last_price("ORCL_US_EQ")) == (Decimal("4.25"), "stooq")
    stooq_history = asyncio.run(yahoo.research("CSCO_US_EQ"))
    assert stooq_history.history[0].data == {"last_price": "4.25"}
    mode["kind"] = "stooq-nd"
    assert asyncio.run(yahoo.last_price("T_US_EQ", position_mark=Decimal("2"))) == (Decimal("2"), "t212")
    mode["kind"] = "none"
    assert asyncio.run(yahoo.last_price("NFLX_US_EQ")) is None
    empty = asyncio.run(yahoo.research("NFLX_US_EQ"))
    assert empty.quote is None
    assert empty.history == []


def test_research_collects_each_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/quote" in url:
            return httpx.Response(200, json={"c": 1})
        if "profile2" in url:
            return httpx.Response(200, json={})
        if "metric" in url:
            return httpx.Response(200, json={"metric": {"pe": 1}})
        if "tiingo" in url:
            return httpx.Response(200, json=[{"close": 1}])
        if "alphavantage" in url:
            return httpx.Response(200, json={"feed": []})
        if "stlouisfed" in url:
            return httpx.Response(200, json={"observations": []})
        if "sec.gov" in url:
            return httpx.Response(200, json={"hits": []})
        return httpx.Response(500, json={"message": "unused"})

    monkeypatch.setattr(
        "src.theo.clients.market_data.get_settings",
        lambda: _keys(
            theo_finnhub_api_key="fh",
            theo_tiingo_api_key="tg",
            theo_alpha_vantage_api_key="av",
            theo_fred_api_key="fd",
            theo_sec_user_agent="ua",
        ),
    )
    client = MarketDataClient(transport=httpx.MockTransport(handler))
    report = asyncio.run(client.research("AAPL_US_EQ"))
    assert report.quote is not None and report.quote.source == "finnhub"
    assert report.profile is None
    assert report.metrics is not None and report.metrics.source == "finnhub"
    assert report.history[0].source == "tiingo"
    assert report.news[0].source == "alpha_vantage"
    assert report.macro[0].source == "fred"
    assert report.filings[0].source == "sec_edgar"


def test_optional_vendor_failures_leave_those_blocks_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "tiingo" in url:
            return httpx.Response(200, json=[])
        if "yahoo" in url:
            return httpx.Response(200, json={"chart": {"result": [{"meta": {"regularMarketPrice": 2}}]}})
        return httpx.Response(503, text="down")

    monkeypatch.setattr(
        "src.theo.clients.market_data.get_settings",
        lambda: _keys(
            theo_tiingo_api_key="tg",
            theo_alpha_vantage_api_key="av",
            theo_fred_api_key="fd",
            theo_sec_user_agent="ua",
        ),
    )
    client = MarketDataClient(transport=httpx.MockTransport(handler))
    report = asyncio.run(client.research("AAPL_US_EQ"))
    assert report.history[0].source == "yahoo"
    assert report.news == []
    assert report.macro == []
    assert report.filings == []


def test_stored_get_serves_a_previous_body_after_a_client_error_and_skips_an_empty_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": datetime(2026, 3, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr("src.theo.stores.replies._now", lambda: clock["now"])
    monkeypatch.setattr("src.theo.clients.market_data.get_settings", lambda: _keys())
    mode = {"kind": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        if "stooq" in str(request.url):
            if mode["kind"] == "limited":
                return httpx.Response(429, json={"message": "later"})
            return httpx.Response(200, text="Symbol,Date,Time,Open,High,Low,Close\nA,d,t,1,2,3,4\n")
        if mode["kind"] in {"bad", "limited"}:
            return httpx.Response(400, json={"message": "no"})
        return httpx.Response(200, json={"chart": {"result": [{"meta": {"regularMarketPrice": 9}}]}})

    client = MarketDataClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(client.last_price("SHOP_US_EQ")) == (Decimal("9"), "yahoo")
    mode["kind"] = "bad"
    assert asyncio.run(client.last_price("SHOP_US_EQ")) == (Decimal("9"), "yahoo")
    mode["kind"] = "limited"
    assert asyncio.run(client.last_price("T_US_EQ")) is None
    assert asyncio.run(client.last_price("T_US_EQ")) is None


def test_price_parsers_reject_a_bad_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.theo.clients.market_data.get_settings", lambda: _keys(theo_finnhub_api_key="fh"))

    def handler(request: httpx.Request) -> httpx.Response:
        if "finnhub" in str(request.url):
            return httpx.Response(200, json={"c": "nope"})
        if "stooq" in str(request.url):
            return httpx.Response(200, text="Symbol,Date,Time,Open,High,Low,Close\nA,d,t,1,2,3,abc\n")
        return httpx.Response(200, json={"chart": {"result": [{"meta": {"regularMarketPrice": "nope"}}]}})

    client = MarketDataClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(client.last_price("BAD_US_EQ", position_mark=Decimal("1"))) == (Decimal("1"), "t212")


def test_market_client_factory_reuses_one_instance() -> None:
    reset_market_data_client()
    try:
        first = get_market_data_client()
        assert get_market_data_client() is first
    finally:
        reset_market_data_client()
