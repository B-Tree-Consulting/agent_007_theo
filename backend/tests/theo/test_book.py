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
