"""Host-rendered case comment bodies. Theo never supplies this text."""

from __future__ import annotations

from decimal import Decimal

from src.theo.schemas import OrderInput, OrderType, Side


def render_placed_comment(
    *,
    ticker: str,
    side: Side | str,
    order_type: OrderType | str,
    quantity: Decimal,
    limit_price: Decimal | None,
    stop_price: Decimal | None,
    notional_czk: Decimal | None,
    fx_date: object,
    fx_czk_per_unit: Decimal | None,
    t212_order_id: str | None,
    environment: str,
) -> str:
    prices = []
    if limit_price is not None:
        prices.append(f"limit {limit_price}")
    if stop_price is not None:
        prices.append(f"stop {stop_price}")
    price_bit = f" ({', '.join(prices)})" if prices else ""
    notional = f"{notional_czk} CZK" if notional_czk is not None else "n/a"
    fx = f"CNB {fx_date} at {fx_czk_per_unit}" if fx_date is not None else "FX n/a"
    broker = t212_order_id or "pending"
    return (
        f"Placed {side} {quantity} {ticker} {order_type}{price_bit}. "
        f"Notional {notional}; {fx}; broker id {broker}; env {environment}."
    )


def render_review_comment(lines: list[str], *, fx_date: object, missing: list[str]) -> str:
    body = "Portfolio review:\n" + "\n".join(lines)
    body += f"\nFX date: {fx_date}."
    if missing:
        body += " Unavailable sources: " + ", ".join(missing) + "."
    return body


def render_cancelled_comment(*, t212_order_id: str, ticker: str, side: str, quantity: Decimal) -> str:
    return f"Cancelled working order {t212_order_id}: {side} {quantity} {ticker}."


def render_approval_comment(
    *,
    rationale: str,
    waited_minutes: int | None,
    approval_record_id: str | None,
) -> str:
    wait = f"{waited_minutes} minutes" if waited_minutes is not None else "unknown interval"
    proof = approval_record_id or "not supplied on confirm"
    return (
        f"Manager approved this large trade after {wait} "
        f"(approval_record_id {proof}). Rationale as submitted: {rationale}"
    )


def render_compensation_fill_comment(*, t212_order_id: str) -> str:
    return (
        f"Compensation could not cancel broker order {t212_order_id} because it had already filled. "
        "The fill stands; no reversing trade was placed."
    )


def order_comment_from_input(inputs: OrderInput, **kwargs: object) -> str:
    return render_placed_comment(
        ticker=inputs.ticker,
        side=inputs.side,
        order_type=inputs.order_type,
        quantity=inputs.quantity,
        limit_price=inputs.limit_price,
        stop_price=inputs.stop_price,
        notional_czk=kwargs.get("notional_czk"),  # type: ignore[arg-type]
        fx_date=kwargs.get("fx_date"),
        fx_czk_per_unit=kwargs.get("fx_czk_per_unit"),  # type: ignore[arg-type]
        t212_order_id=kwargs.get("t212_order_id"),  # type: ignore[arg-type]
        environment=str(kwargs.get("environment") or "demo"),
    )
