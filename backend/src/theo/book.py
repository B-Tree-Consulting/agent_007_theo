"""Book rules: notional, stop side, position cap, signed quantity."""

from __future__ import annotations

from decimal import Decimal

from src.theo.errors import STOP_PRICE_INVALID, TheoError
from src.theo.schemas import OrderInput, OrderType, Side


def signed_quantity(side: Side | str, quantity: Decimal) -> Decimal:
    qty = Decimal(quantity)
    if qty <= 0:
        raise ValueError("quantity must be positive")
    if side == Side.sell or str(getattr(side, "value", side)) == Side.sell.value:
        return -qty
    return qty


def notional_price(inputs: OrderInput, last_price: Decimal | None) -> Decimal | None:
    if inputs.order_type in {OrderType.limit, OrderType.stop_limit}:
        return inputs.limit_price
    if inputs.order_type == OrderType.stop:
        return inputs.stop_price
    return last_price


def missing_order_fields(inputs: OrderInput) -> list[str]:
    missing: list[str] = []
    if inputs.order_type in {OrderType.limit, OrderType.stop_limit} and inputs.limit_price is None:
        missing.append("limit_price")
    if inputs.order_type in {OrderType.stop, OrderType.stop_limit} and inputs.stop_price is None:
        missing.append("stop_price")
    if inputs.order_type != OrderType.market and inputs.time_validity is None:
        missing.append("time_validity")
    return missing


def notional_czk(quantity: Decimal, price: Decimal, fx_czk_per_unit: Decimal) -> Decimal:
    return (quantity * price * fx_czk_per_unit).quantize(Decimal("0.01"))


def assert_stop_side(inputs: OrderInput, last_price: Decimal) -> None:
    if inputs.stop_price is None:
        return
    if inputs.side == Side.sell and inputs.stop_price >= last_price:
        raise TheoError(STOP_PRICE_INVALID, "Sell stop-loss trigger must sit below the last price")
    if inputs.side == Side.buy and inputs.stop_price <= last_price:
        raise TheoError(STOP_PRICE_INVALID, "Buy stop trigger must sit above the last price")


def _signed_order_quantity(order: dict) -> Decimal:
    signed = order.get("signed_quantity")
    if signed is not None:
        return Decimal(str(signed))
    qty = Decimal(str(order.get("quantity") or 0))
    side = order.get("side")
    if side == Side.sell or str(getattr(side, "value", side)) == Side.sell.value:
        return -abs(qty)
    return qty


def working_sell_quantity(orders: list[dict], ticker: str) -> Decimal:
    total = Decimal("0")
    for order in orders:
        if order.get("ticker") != ticker:
            continue
        qty = _signed_order_quantity(order)
        if qty < 0:
            total += -qty
    return total


def held_tickers(positions: list[dict]) -> set[str]:
    return {str(p["ticker"]) for p in positions if Decimal(str(p.get("quantity") or 0)) > 0}


def working_buy_new_names(orders: list[dict], held: set[str]) -> set[str]:
    names: set[str] = set()
    for order in orders:
        ticker = str(order.get("ticker") or "")
        if not ticker or ticker in held:
            continue
        if _signed_order_quantity(order) > 0:
            names.add(ticker)
    return names
