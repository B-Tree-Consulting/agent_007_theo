"""Unit tests for Theo book rules, CNB parsing, and symbols."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.theo.book import missing_order_fields, notional_czk, signed_quantity
from src.theo.clients.cnb import parse_denni_kurz
from src.theo.errors import BROKER_AMBIGUOUS, STOP_PRICE_INVALID, TheoError
from src.theo.schemas import LimitOrderInput, MarketOrderInput, OrderInput, OrderType, Side, TimeValidity
from src.theo.symbol import vendor_symbol


def test_signed_quantity_sell_is_negative() -> None:
    assert signed_quantity(Side.sell, Decimal("1.5")) == Decimal("-1.5")
    assert signed_quantity(Side.buy, Decimal("1.5")) == Decimal("1.5")


def test_notional_uses_fx() -> None:
    assert notional_czk(Decimal("2"), Decimal("100"), Decimal("23")) == Decimal("4600.00")


def test_typed_market_converts_without_prices() -> None:
    order = MarketOrderInput(ticker="AAPL_US_EQ", side=Side.buy, quantity=Decimal("1")).to_order_input()
    assert order.order_type == OrderType.market
    assert order.limit_price is None
    assert missing_order_fields(order) == []


def test_typed_limit_requires_price_and_validity() -> None:
    order = LimitOrderInput(
        ticker="AAPL_US_EQ",
        side=Side.buy,
        quantity=Decimal("1"),
        limit_price=Decimal("148"),
        time_validity=TimeValidity.DAY,
    ).to_order_input()
    assert order.order_type == OrderType.limit
    assert missing_order_fields(order) == []


def test_missing_limit_price() -> None:
    inputs = OrderInput(
        ticker="AAPL_US_EQ",
        side=Side.buy,
        quantity=Decimal("1"),
        order_type=OrderType.limit,
    )
    assert "limit_price" in missing_order_fields(inputs)
    assert "time_validity" in missing_order_fields(inputs)


def test_stop_side_rejected() -> None:
    from src.theo.book import assert_stop_side

    inputs = OrderInput(
        ticker="AAPL_US_EQ",
        side=Side.sell,
        quantity=Decimal("1"),
        order_type=OrderType.stop,
        stop_price=Decimal("160"),
        time_validity=TimeValidity.GOOD_TILL_CANCEL,
    )
    with pytest.raises(TheoError) as exc:
        assert_stop_side(inputs, Decimal("150"))
    assert exc.value.code == STOP_PRICE_INVALID


def test_parse_cnb_usd_row() -> None:
    text = "06.10.2026 #192\nzemě|měna|množství|kód|kurz\nUSA|dolar|1|USD|23,150\nEMU|euro|1|EUR|25,000\n"
    rate, fixing_date = parse_denni_kurz(text, currency="USD")
    assert rate == Decimal("23.150")
    assert fixing_date.isoformat() == "2026-10-06"


def test_vendor_symbol_strips_eq_suffix() -> None:
    assert vendor_symbol("AAPL_US_EQ", overrides={}) == "AAPL"
    assert vendor_symbol("AAPL_US_EQ", overrides={"AAPL_US_EQ": "AAPL.US"}) == "AAPL.US"


def test_working_sell_uses_side_when_quantity_is_positive() -> None:
    from src.theo.book import working_sell_quantity

    orders = [
        {"ticker": "AAPL_US_EQ", "quantity": Decimal("2"), "side": Side.sell},
        {"ticker": "AAPL_US_EQ", "quantity": Decimal("1"), "signed_quantity": Decimal("-1")},
    ]
    assert working_sell_quantity(orders, "AAPL_US_EQ") == Decimal("3")


def _dispatch_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status="dispatching",
        t212_order_id=None,
        submitted_at=datetime.now(timezone.utc),
    )


def _market() -> OrderInput:
    return MarketOrderInput(ticker="AAPL_US_EQ", side=Side.buy, quantity=Decimal("1")).to_order_input()


def test_unmatched_dispatch_retry_does_not_place_again(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.theo.fakes import FakeT212

    from src.theo.actions import PLACE_ACTIONS
    from src.theo.stores import intents as intent_store

    action = PLACE_ACTIONS["place_market_equity_order"](comments=None)
    row = _dispatch_row()
    fake = FakeT212()
    marked: list[tuple] = []

    def _existing(_inputs):
        return row

    def _mark(intent_id, status, **kwargs):
        marked.append((intent_id, status, kwargs.get("error_code")))

    monkeypatch.setattr(action, "_ensure_dispatching_row", _existing)
    monkeypatch.setattr("src.theo.actions.get_t212_client", lambda: fake)
    monkeypatch.setattr(intent_store, "mark_status", _mark)

    with pytest.raises(TheoError) as caught:
        asyncio.run(action.post_broker_order(_market()))

    assert caught.value.code == BROKER_AMBIGUOUS
    assert fake.placed == []
    assert marked == [(row.id, "failed", BROKER_AMBIGUOUS)]


def test_matched_dispatch_retry_adopts_the_broker_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.theo.fakes import FakeT212

    from src.theo.actions import PLACE_ACTIONS
    from src.theo.stores import intents as intent_store

    action = PLACE_ACTIONS["place_market_equity_order"](comments=None)
    row = _dispatch_row()
    fake = FakeT212()
    fake.orders.append(
        {
            "t212_order_id": "501",
            "ticker": "AAPL_US_EQ",
            "signed_quantity": Decimal("1"),
            "created_at": row.submitted_at,
        }
    )

    monkeypatch.setattr(action, "_ensure_dispatching_row", lambda _inputs: row)
    monkeypatch.setattr("src.theo.actions.get_t212_client", lambda: fake)
    monkeypatch.setattr(intent_store, "mark_status", lambda *args, **kwargs: None)

    adopted = asyncio.run(action.post_broker_order(_market()))

    assert adopted == "501"
    assert fake.placed == []


def test_fresh_dispatch_still_places(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.theo.fakes import FakeT212

    from src.theo.actions import PLACE_ACTIONS
    from src.theo.stores import intents as intent_store

    action = PLACE_ACTIONS["place_market_equity_order"](comments=None)
    row = _dispatch_row()
    fake = FakeT212()

    def _new(_inputs):
        action._fresh_dispatch = True
        return row

    monkeypatch.setattr(action, "_ensure_dispatching_row", _new)
    monkeypatch.setattr("src.theo.actions.get_t212_client", lambda: fake)
    monkeypatch.setattr(intent_store, "mark_status", lambda *args, **kwargs: None)

    order_id = asyncio.run(action.post_broker_order(_market()))

    assert order_id == "101"
    assert len(fake.placed) == 1


def test_t212_retries_rate_limit_then_reads_cash() -> None:
    import time

    import httpx

    from src.theo.clients.t212 import T212Client

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                headers={"x-ratelimit-reset": str(int(time.time()) - 1)},
                json={"message": "Too Many Requests"},
            )
        return httpx.Response(200, json={"free": "10", "invested": "0", "total": "10"})

    client = T212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="k",
        api_secret="s",
        transport=httpx.MockTransport(handler),
    )
    cash = asyncio.run(client.account_cash())
    assert cash["free"] == Decimal("10")
    assert calls["n"] == 2


def test_metadata_instruments_is_cached_for_five_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from src.theo.clients.t212 import T212Client

    calls = {"n": 0}
    clock = {"t": 1_000.0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(200, json=[{"ticker": "AAPL_US_EQ", "currencyCode": "USD"}])

    monkeypatch.setattr("src.theo.clients.t212.time.monotonic", lambda: clock["t"])
    client = T212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="k",
        api_secret="s",
        transport=httpx.MockTransport(handler),
    )

    first = asyncio.run(client.metadata_instruments())
    clock["t"] += 299
    second = asyncio.run(client.metadata_instruments())
    clock["t"] += 1
    third = asyncio.run(client.metadata_instruments())

    assert first[0]["ticker"] == "AAPL_US_EQ"
    assert second[0]["ticker"] == "AAPL_US_EQ"
    assert third[0]["ticker"] == "AAPL_US_EQ"
    assert calls["n"] == 2


def test_metadata_exchanges_is_cached_for_five_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from src.theo.clients.t212 import T212Client

    calls = {"n": 0}
    clock = {"t": 1_000.0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(200, json=[{"id": 7, "name": "XNAS", "timeZone": "America/New_York"}])

    monkeypatch.setattr("src.theo.clients.t212.time.monotonic", lambda: clock["t"])
    client = T212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="k",
        api_secret="s",
        transport=httpx.MockTransport(handler),
    )

    first = asyncio.run(client.metadata_exchanges())
    clock["t"] += 299
    second = asyncio.run(client.metadata_exchanges())
    clock["t"] += 1
    third = asyncio.run(client.metadata_exchanges())

    assert first[0]["working_schedule_id"] == "7"
    assert second[0]["name"] == "XNAS"
    assert third[0]["timezone"] == "America/New_York"
    assert calls["n"] == 2


def test_metadata_exchanges_skips_a_bad_row_and_does_not_cache_a_failure() -> None:
    import httpx

    from src.theo.clients.t212 import T212Client
    from src.theo.errors import TheoError

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "Too Many Requests"})
        return httpx.Response(200, json={"items": [{"id": 7, "name": "XNAS"}, "skip-me"]})

    client = T212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="k",
        api_secret="s",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TheoError):
        asyncio.run(client.metadata_exchanges())
    rows = asyncio.run(client.metadata_exchanges())

    assert calls["n"] == 2
    assert [row["name"] for row in rows] == ["XNAS"]


def test_metadata_exchanges_waiter_reuses_the_list_just_stored() -> None:
    import httpx

    from src.theo.clients.t212 import T212Client

    class _Gate(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            del request
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return httpx.Response(200, json=[{"id": 7, "name": "XNAS"}])

    gate = _Gate()
    client = T212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="k",
        api_secret="s",
        transport=gate,
    )

    async def _run() -> None:
        first = asyncio.create_task(client.metadata_exchanges())
        await gate.started.wait()
        second = asyncio.create_task(client.metadata_exchanges())
        await asyncio.sleep(0)
        gate.release.set()
        rows_a, rows_b = await asyncio.gather(first, second)
        assert rows_a[0]["name"] == "XNAS"
        assert rows_b[0]["name"] == "XNAS"
        assert gate.calls == 1

    asyncio.run(_run())


def test_place_order_error_keeps_broker_body_and_reads_stay_short() -> None:
    import httpx

    from src.theo.clients.t212 import T212Client
    from src.theo.errors import TheoError
    from src.theo.schemas import MarketOrderInput, Side

    body = '{"code":"instrument-not-tradable","detail":"QQQ_EQ is not open"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=body)

    client = T212Client(
        base_url="https://demo.trading212.com/api/v0",
        api_key="k",
        api_secret="s",
        transport=httpx.MockTransport(handler),
    )
    order = MarketOrderInput(ticker="QQQ_EQ", side=Side.buy, quantity=Decimal("1")).to_order_input()
    try:
        asyncio.run(client.place_order(order))
    except TheoError as exc:
        assert body in exc.message
    else:
        raise AssertionError("place_order should reject")
    try:
        asyncio.run(client.account_cash())
    except TheoError as exc:
        assert exc.message == "Bad Request"
        assert "instrument-not-tradable" not in exc.message
    else:
        raise AssertionError("account_cash should reject")


def test_publish_execution_broker_response_copies_only_the_step_failure() -> None:
    from src.theo.actions import _publish_execution_broker_response

    _publish_execution_broker_response(SimpleNamespace(result=None))
    untouched = SimpleNamespace(assertions=[], outputs=None)
    _publish_execution_broker_response(SimpleNamespace(result=untouched))
    assert untouched.outputs is None

    merged = SimpleNamespace(
        assertions=[SimpleNamespace(id="effect-error", evidence="post_broker_order blew up")],
        outputs={"keep": 1},
    )
    _publish_execution_broker_response(SimpleNamespace(result=merged))
    assert merged.outputs == {"keep": 1, "broker_response": "post_broker_order blew up"}

    wrapped = SimpleNamespace(
        assertions=[
            SimpleNamespace(id="other", evidence="no"),
            SimpleNamespace(id="effect-error", evidence="Step 'post_broker_order' raised: BODY"),
        ],
        outputs=None,
    )
    _publish_execution_broker_response(SimpleNamespace(result=wrapped))
    assert wrapped.outputs == {"broker_response": "BODY"}


def test_plan_token_ignores_price_drift_on_the_same_side_of_the_gate() -> None:
    from src.theo.actions import PLACE_ACTIONS, OrderFacts
    from src.theo.snapshot import BookSnapshot

    action = PLACE_ACTIONS["place_large_market_equity_order"](comments=None)
    order = _market()
    steps = [SimpleNamespace(name="post_broker_order")]

    def token(last_price: str) -> str:
        book = BookSnapshot(
            positions=[],
            orders=[],
            cash_free=Decimal("100000"),
            cash_invested=Decimal("0"),
            cash_total=Decimal("100000"),
            fx_czk_per_unit=Decimal("20"),
            fx_date=None,
            fx_source=None,
            last_price=Decimal(last_price),
            quote_source="test",
            whitelist=(),
            max_positions=10,
            attention_notional=Decimal("10000"),
            environment="demo",
        )
        return action._plan_token(order, OrderFacts(book=book), steps)

    # 1 share * 400 * 20 = 8_000 CZK, still under 10_000. 600 * 20 = 12_000, over the gate.
    under_a = token("400")
    under_b = token("450")
    over = token("600")
    assert under_a == under_b
    assert under_a != over

    from src.theo.actions import _at_or_under_approval_threshold

    assert _at_or_under_approval_threshold(order, OrderFacts()) is None
    assert _at_or_under_approval_threshold(order, OrderFacts(book=SimpleNamespace())) is None
    blind = SimpleNamespace(notional_for=lambda _order: None, attention_notional=Decimal("10000"))
    assert _at_or_under_approval_threshold(order, OrderFacts(book=blind)) is None
