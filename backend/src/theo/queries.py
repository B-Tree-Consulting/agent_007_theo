"""Read-only Theo catalog tools."""

from __future__ import annotations

import inspect
from typing import Any

from agentstepkit import assert_that
from bfa import ExecuteContext

from src.config import get_settings
from src.theo.clients.market_data import get_market_data_client
from src.theo.errors import INSTRUMENT_NOT_FOUND, RESEARCH_NOT_PERMITTED, TOOL_VERSION
from src.theo.schemas import (
    AccountSummaryOutput,
    EmptyInput,
    ExchangesOutput,
    ExchangeView,
    GetExchangesInput,
    GetInstrumentsInput,
    GetTitleResearchInput,
    GetTradeIntentsInput,
    InstrumentsOutput,
    InstrumentView,
    OpenOrderView,
    OpenOrdersOutput,
    PortfolioOutput,
    PositionView,
    TitleResearchOutput,
    TradeIntentView,
    TradeIntentsOutput,
    WhitelistOutput,
)
from src.theo.settings import attention_notional, parse_whitelist, t212_environment
from src.theo.snapshot import load_account_snapshot
from src.theo.stores import intents as intent_store
from src.shared.invoke_scope import get_invoke_case_id

DESCRIPTIONS = {
    "get_account_summary": (
        "Read the Trading 212 account's cash available to trade, invested amount, and total equity. "
        "Use this before any buy to check cash_available_czk. This call does not carry a share price "
        "or the crown rate. The place tool loads those. Returns no secrets."
    ),
    "get_portfolio": (
        "List the equity positions currently held on the account, each with quantity, average price, "
        "last price, CZK market value, and unrealised profit or loss. Use this to see what the book "
        "holds before deciding anything. Does not include working orders."
    ),
    "get_open_orders": (
        "List orders currently working at the broker but not yet filled, including the stop and limit "
        "prices and the broker order id needed to cancel one. Use this to avoid ordering the same thing "
        "twice and to find an order to cancel."
    ),
    "get_whitelist": (
        "List the tickers this account is permitted to buy, along with max_names and approval_notional_czk. "
        "Use those figures. Do not assume 20 names or 10000 CZK. Use this before proposing any buy. "
        "A ticker not on this list cannot be bought, however good it looks."
    ),
    "get_instruments": (
        "List Trading 212 instrument records for names you care about: ticker, name, ISIN, type, currency, "
        "whether the name allows extended hours, max open quantity, quantity_step, broker_last, "
        "fx_czk_per_unit, and working_schedule_id. Do not call this to price or size an order; the place "
        "tool does that. Use working_schedule_id with get_exchanges for the venue calendar. With no "
        "ticker, returns the whitelist plus names currently held, not the whole Trading 212 universe."
    ),
    "get_exchanges": (
        "List Trading 212 exchanges and their working schedules: timezone, OPEN, CLOSE, break, pre-market, "
        "after-hours, and overnight events. Use this with get_instruments.working_schedule_id. The host "
        "does not compute whether the venue is open now."
    ),
    "get_title_research": (
        "Gather free-tier market information about one ticker that is on the whitelist or currently held. "
        "Each block names its source. It contains no recommendation. Do not use its last price to choose "
        "a place tool or to size an order. The place tool prices the order."
    ),
    "get_trade_intents": (
        "List the orders this BFA has recorded for the current case, including which are awaiting the "
        "manager's approval and which failed and why. A failed row includes error_code and the broker "
        "message from the execution attempt. This reads the case record, not a live broker search. "
        "Use this to see whether a trade you proposed earlier has gone through before proposing it again."
    ),
}


async def get_account_summary(self: Any, inputs: EmptyInput) -> AccountSummaryOutput:
    del self, inputs
    snap = await load_account_snapshot()
    return AccountSummaryOutput(
        cash_available_czk=snap.cash_free,
        invested_czk=snap.cash_invested,
        total_equity_czk=snap.cash_total,
        currency="CZK",
    )


def portfolio_from_snapshot(snap: Any) -> PortfolioOutput:
    positions = []
    for row in snap.positions:
        qty = row["quantity"]
        last = row.get("last_price")
        currency = str(row.get("currency") or "USD").upper()
        fx = snap.fx_by_currency.get(currency) or snap.fx_czk_per_unit
        mv = None
        if last is not None and fx is not None:
            mv = qty * last * fx
        positions.append(
            PositionView(
                ticker=row["ticker"],
                quantity=qty,
                average_price=row.get("average_price"),
                last_price=last,
                quote_source="t212" if last is not None else None,
                market_value_czk=mv,
                unrealized_pl=row.get("ppl"),
            )
        )
    return PortfolioOutput(
        positions=positions,
        position_count=len(positions),
        max_positions=snap.max_positions,
    )


async def get_portfolio(self: Any, inputs: EmptyInput) -> PortfolioOutput:
    del self, inputs
    return portfolio_from_snapshot(await load_account_snapshot())


async def get_open_orders(self: Any, inputs: EmptyInput) -> OpenOrdersOutput:
    del self, inputs
    snap = await load_account_snapshot()
    case_id = get_invoke_case_id()
    tracked = set()
    if case_id:
        tracked = {row.t212_order_id for row in intent_store.list_for_case(case_id) if row.t212_order_id}
    orders = [
        OpenOrderView(
            t212_order_id=row["t212_order_id"],
            ticker=row["ticker"],
            side=row["side"],
            order_type=row["order_type"],
            quantity=row["quantity"],
            limit_price=row.get("limit_price"),
            stop_price=row.get("stop_price"),
            time_validity=row.get("time_validity"),
            created_at=row.get("created_at"),
            tracked_by_host=row["t212_order_id"] in tracked,
        )
        for row in snap.orders
    ]
    return OpenOrdersOutput(orders=orders)


async def get_whitelist(self: Any, inputs: EmptyInput) -> WhitelistOutput:
    del self, inputs
    settings = get_settings()
    return WhitelistOutput(
        tickers=list(parse_whitelist(settings)),
        max_names=settings.theo_max_positions,
        approval_notional_czk=attention_notional(settings),
        environment=t212_environment(settings),
    )


async def get_title_research(self: Any, inputs: GetTitleResearchInput) -> TitleResearchOutput:
    del self
    snap = await load_account_snapshot(ticker=inputs.ticker)
    mark = next((p.get("last_price") for p in snap.positions if p.get("ticker") == inputs.ticker), None)
    return await get_market_data_client().research(inputs.ticker, position_mark=mark)


_PUBLIC_STATUS = {
    "awaiting_approval": "awaiting_approval",
    "dispatching": "working",
    "executed": "working",
    "filled": "filled",
}


def _public_status(status: str) -> str:
    return _PUBLIC_STATUS.get(status, status)


async def _research_ticker_allowed(inputs: GetTitleResearchInput, ctx: Any, facts: Any) -> tuple[bool, str] | bool:
    del ctx, facts
    allowed = set(parse_whitelist())
    snap = await load_account_snapshot()
    held = {str(row.get("ticker")) for row in snap.positions if row.get("quantity")}
    if inputs.ticker in allowed or inputs.ticker in held:
        return True
    return False, f"{inputs.ticker} is neither on the whitelist nor currently held"


async def _instrument_exists(inputs: GetInstrumentsInput, ctx: Any, facts: Any) -> tuple[bool, str] | bool:
    del ctx, facts
    if not inputs.ticker:
        return True
    from src.theo.clients.t212 import get_t212_client

    rows = await get_t212_client().metadata_instruments()
    if any(row.get("ticker") == inputs.ticker for row in rows):
        return True
    return False, f"{inputs.ticker} is not listed on this Trading 212 account"


async def get_instruments(self: Any, inputs: GetInstrumentsInput) -> InstrumentsOutput:
    del self
    from src.theo.clients.t212 import get_t212_client

    snap = await load_account_snapshot(ticker=inputs.ticker)
    whitelist = set(parse_whitelist())
    held = {str(row.get("ticker")) for row in snap.positions}
    rows = await get_t212_client().metadata_instruments()
    if inputs.ticker:
        rows = [row for row in rows if row.get("ticker") == inputs.ticker]
    else:
        wanted = whitelist | held
        rows = [row for row in rows if row.get("ticker") in wanted]
    marks = {str(row.get("ticker")): row.get("last_price") for row in snap.positions}
    instruments = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        currency = str(row.get("currency") or "USD").upper()
        instruments.append(
            InstrumentView(
                ticker=ticker,
                name=row.get("name"),
                isin=row.get("isin"),
                type=row.get("type"),
                currency=row.get("currency"),
                extended_hours=bool(row.get("extended_hours")),
                max_open_quantity=row.get("max_open_quantity"),
                quantity_step=row.get("quantity_step"),
                broker_last=marks.get(ticker),
                fx_czk_per_unit=snap.fx_by_currency.get(currency),
                working_schedule_id=row.get("working_schedule_id"),
                on_whitelist=ticker in whitelist,
            )
        )
    return InstrumentsOutput(instruments=instruments)


async def get_exchanges(self: Any, inputs: GetExchangesInput) -> ExchangesOutput:
    del self
    from src.theo.clients.t212 import get_t212_client

    rows = await get_t212_client().metadata_exchanges()
    if inputs.working_schedule_id:
        rows = [row for row in rows if str(row.get("working_schedule_id")) == inputs.working_schedule_id]
    return ExchangesOutput(
        exchanges=[
            ExchangeView(
                working_schedule_id=row.get("working_schedule_id"),
                name=row.get("name"),
                timezone=row.get("timezone"),
                events=list(row.get("events") or []),
            )
            for row in rows
        ]
    )


async def get_trade_intents(self: Any, inputs: GetTradeIntentsInput) -> TradeIntentsOutput:
    del self
    case_id = get_invoke_case_id()
    if not case_id:
        return TradeIntentsOutput(intents=[])
    rows = intent_store.list_for_case(case_id, status=None, limit=50)
    if inputs.status is not None:
        wanted = inputs.status.value
        rows = [row for row in rows if _public_status(row.status) == wanted]
    rows = rows[: inputs.limit]
    return TradeIntentsOutput(
        intents=[
            TradeIntentView(
                intent_id=row.id,
                status=_public_status(row.status),
                ticker=row.ticker,
                side=row.side,
                order_type=row.order_type,
                quantity=row.quantity,
                notional_czk=row.notional_czk,
                submitted_at=row.submitted_at,
                t212_order_id=row.t212_order_id,
                error_code=row.error_code,
                broker_message=row.broker_message,
            )
            for row in rows
        ]
    )


def _query_kwargs(name: str, describe: str, input_model: type, output_model: type) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "name": name,
        "describe": describe,
        "version": TOOL_VERSION,
        "risk": "low",
        "execute_context": ExecuteContext.DE_AUTONOMOUS,
        "input_model": input_model,
        "output_model": output_model,
    }
    return kwargs


get_title_research = assert_that.pre(
    RESEARCH_NOT_PERMITTED,
    "Research is limited to whitelist tickers and names currently held",
    check=_research_ticker_allowed,
)(get_title_research)
get_instruments = assert_that.pre(
    INSTRUMENT_NOT_FOUND,
    "The ticker is not listed on this Trading 212 account",
    check=_instrument_exists,
)(get_instruments)


def register(host_cls: type) -> None:
    specs = [
        ("get_account_summary", DESCRIPTIONS["get_account_summary"], EmptyInput, AccountSummaryOutput, get_account_summary),
        ("get_portfolio", DESCRIPTIONS["get_portfolio"], EmptyInput, PortfolioOutput, get_portfolio),
        ("get_open_orders", DESCRIPTIONS["get_open_orders"], EmptyInput, OpenOrdersOutput, get_open_orders),
        ("get_whitelist", DESCRIPTIONS["get_whitelist"], EmptyInput, WhitelistOutput, get_whitelist),
        ("get_instruments", DESCRIPTIONS["get_instruments"], GetInstrumentsInput, InstrumentsOutput, get_instruments),
        ("get_exchanges", DESCRIPTIONS["get_exchanges"], GetExchangesInput, ExchangesOutput, get_exchanges),
        ("get_title_research", DESCRIPTIONS["get_title_research"], GetTitleResearchInput, TitleResearchOutput, get_title_research),
        ("get_trade_intents", DESCRIPTIONS["get_trade_intents"], GetTradeIntentsInput, TradeIntentsOutput, get_trade_intents),
    ]
    query = host_cls.query
    for name, describe, input_model, output_model, fn in specs:
        kwargs = _query_kwargs(name, describe, input_model, output_model)
        if "case_tool_class" in inspect.signature(query).parameters:
            kwargs["case_tool_class"] = "read"
        query(**kwargs)(fn)
        setattr(host_cls, fn.__name__, fn)
