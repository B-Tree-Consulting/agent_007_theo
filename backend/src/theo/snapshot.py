"""Read-side snapshot used by queries and action guards."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from src.config import get_settings
from src.theo.book import notional_czk, notional_price
from src.theo.clients.cnb import load_fixing
from src.theo.clients.market_data import get_market_data_client
from src.theo.clients.t212 import current_t212_environment, get_t212_client
from src.shared.invoke_scope import get_invoke_account_cache, get_invoke_correlation_id
from src.theo.schemas import OrderInput
from src.theo.settings import attention_notional, parse_whitelist
from src.theo.stores import intents as intent_store


class IntentView(BaseModel):
    """JSON-safe projection so plan tokens can hash the book snapshot."""

    id: str
    status: str
    payload_hash: str
    error_code: str | None = None
    broker_message: str | None = None
    t212_order_id: str | None = None


def intent_view(row: Any) -> IntentView | None:
    if row is None:
        return None
    return IntentView(
        id=str(row.id),
        status=row.status,
        payload_hash=row.payload_hash,
        error_code=row.error_code,
        broker_message=row.broker_message,
        t212_order_id=row.t212_order_id,
    )


@dataclass
class BookSnapshot:
    positions: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    cash_free: Decimal
    cash_invested: Decimal
    cash_total: Decimal
    fx_czk_per_unit: Decimal | None
    fx_date: date | None
    fx_source: str | None
    last_price: Decimal | None
    quote_source: str | None
    whitelist: tuple[str, ...]
    max_positions: int
    attention_notional: Decimal
    environment: str
    quantity_step: Decimal | None = None
    fx_by_currency: dict[str, Decimal] = field(default_factory=dict)
    existing_intent: Any | None = None
    pending_same_ticker: Any | None = None
    error_code: str | None = field(default=None)
    error_message: str | None = field(default=None)

    def notional_for(self, inputs: OrderInput) -> Decimal | None:
        price = notional_price(inputs, self.last_price)
        if price is None or self.fx_czk_per_unit is None:
            return None
        return notional_czk(inputs.quantity, price, self.fx_czk_per_unit)


async def load_account_snapshot(*, ticker: str | None = None) -> BookSnapshot:
    cache = get_invoke_account_cache()
    key = ticker or ""
    if cache is not None and key in cache:
        return cache[key]
    snap = await _fetch_account_snapshot(ticker=ticker)
    if cache is not None:
        cache[key] = snap
    return snap


async def _fetch_account_snapshot(*, ticker: str | None = None) -> BookSnapshot:
    settings = get_settings()
    t212 = get_t212_client()
    cash = await t212.account_cash()
    positions = await t212.positions()
    orders = await t212.open_orders()
    fx_rate = fx_date = fx_source = None
    quantity_step = None
    fx_by_currency: dict[str, Decimal] = {}
    fx_meta: dict[str, tuple[Decimal, date, str]] = {}
    try:
        instruments = await t212.metadata_instruments()
    except Exception:
        instruments = []
    by_ticker = {row["ticker"]: row for row in instruments}
    held_names = {str(row.get("ticker")) for row in positions if row.get("ticker")}
    whitelist = set(parse_whitelist(settings))
    currencies = {
        str(row.get("currency") or "").upper()
        for row in positions
        if row.get("currency")
    }
    for item in by_ticker.values():
        if item.get("ticker") in whitelist or item.get("ticker") in held_names:
            if item.get("currency"):
                currencies.add(str(item["currency"]).upper())
    if ticker and ticker in by_ticker and by_ticker[ticker].get("currency"):
        currencies.add(str(by_ticker[ticker]["currency"]).upper())
        quantity_step = by_ticker[ticker].get("quantity_step")
    if not currencies:
        currencies.add("USD")
    for code in sorted(currencies):
        try:
            if code == "CZK":
                fx_meta[code] = (Decimal("1"), date.today(), "account")
            else:
                row = await load_fixing(code)
                fx_meta[code] = (row.czk_per_unit, row.fixing_date, row.source)
            fx_by_currency[code] = fx_meta[code][0]
        except Exception:
            continue
    chosen = "USD"
    if ticker and ticker in by_ticker and by_ticker[ticker].get("currency"):
        chosen = str(by_ticker[ticker]["currency"]).upper()
    if chosen in fx_meta:
        fx_rate, fx_date, fx_source = fx_meta[chosen]
    elif fx_meta:
        fx_rate, fx_date, fx_source = next(iter(fx_meta.values()))
    last_price = quote_source = None
    if ticker:
        mark = next((p.get("last_price") for p in positions if p.get("ticker") == ticker), None)
        quoted = await get_market_data_client().last_price(ticker, position_mark=mark)
        if quoted is not None:
            last_price, quote_source = quoted
    return BookSnapshot(
        positions=positions,
        orders=orders,
        cash_free=cash["free"],
        cash_invested=cash["invested"],
        cash_total=cash["total"],
        fx_czk_per_unit=fx_rate,
        fx_date=fx_date,
        fx_source=fx_source,
        last_price=last_price,
        quote_source=quote_source,
        whitelist=parse_whitelist(settings),
        max_positions=settings.theo_max_positions,
        attention_notional=attention_notional(settings),
        environment=current_t212_environment(),
        quantity_step=quantity_step,
        fx_by_currency=fx_by_currency,
    )


async def load_order_snapshot(case_id: str, inputs: OrderInput, *, tool_name: str) -> BookSnapshot:
    intent_store.sweep_abandoned(case_id)
    snap = await load_account_snapshot(ticker=inputs.ticker)
    correlation = intent_store.clean_correlation(get_invoke_correlation_id())
    row = intent_store.get_active(case_id, correlation, tool_name) if correlation else None
    superseded = None
    if (
        row is not None
        and row.payload_hash != intent_store.payload_hash(inputs)
        and row.status in intent_store.REPLACEABLE_STATUSES
    ):
        superseded = row
        row = None
    snap.existing_intent = intent_view(row)
    pending = intent_store.pending_for_ticker(case_id, inputs.ticker)
    if superseded is not None and pending is not None and pending.id == superseded.id:
        pending = None
    snap.pending_same_ticker = intent_view(pending)
    return snap


def as_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
