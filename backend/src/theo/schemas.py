"""Pydantic input/output models for Theo tools."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Side(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"
    limit = "limit"
    stop = "stop"
    stop_limit = "stop_limit"


class TimeValidity(str, Enum):
    DAY = "DAY"
    GOOD_TILL_CANCEL = "GOOD_TILL_CANCEL"


class IntentStatus(str, Enum):
    dispatching = "dispatching"
    awaiting_approval = "awaiting_approval"
    executed = "executed"
    abandoned = "abandoned"
    failed = "failed"
    cancelled = "cancelled"


def _positive_decimal(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("must be greater than zero")
    return value


class EmptyInput(BaseModel):
    """No caller inputs."""


class GetTitleResearchInput(BaseModel):
    ticker: str = Field(description="A whitelist ticker or a name currently held, for example AAPL_US_EQ.")


class TradeIntentFilter(str, Enum):
    awaiting_approval = "awaiting_approval"
    working = "working"
    filled = "filled"


class GetTradeIntentsInput(BaseModel):
    status: TradeIntentFilter | None = Field(
        default=None,
        description="Optional filter: awaiting_approval, working, or filled.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum number of intents to return.",
    )


class ReviewPortfolioInput(BaseModel):
    include_research: bool = Field(
        default=True,
        description="When true, attach the free-tier research pack per name.",
    )


TICKER_DESC = (
    "Trading 212 instrument ticker, for example AAPL_US_EQ. Must be on the whitelist for a buy. "
    "Ask the user which name if they have not said."
)
SIDE_DESC = (
    "buy or sell. Always use a positive quantity; the host sends the broker's negative quantity for a sell. "
    "Ask if the user has not said which."
)
QUANTITY_DESC = (
    "Number of shares, a positive multiple of get_instruments.quantity_step. Never a crown amount. "
    "If the user spoke in crowns, convert with get_instruments and floor to quantity_step. Ask if missing."
)
LIMIT_PRICE_DESC = (
    "Limit price per share in the instrument's currency. Ask the user; do not invent a price."
)
STOP_PRICE_DESC = (
    "Trigger price per share. Below the last price for a sell stop-loss, above it for a buy stop. "
    "Ask the user; do not invent a price."
)
TIME_VALIDITY_DESC = (
    "DAY expires today; GOOD_TILL_CANCEL rests until filled or cancelled. Ask if the user has not said which."
)
EXTENDED_HOURS_DESC = "Allow execution outside regular hours."
RATIONALE_DESC = (
    "Why this trade, in one or two sentences. The manager reads it when approving. "
    "Plain business reasoning only, no personal or account data."
)


class OrderInput(BaseModel):
    """Canonical order payload used internally by book, intents, and Trading 212."""

    ticker: str = Field(description=TICKER_DESC)
    side: Side = Field(description=SIDE_DESC)
    quantity: Decimal = Field(max_digits=20, decimal_places=8, description=QUANTITY_DESC)
    order_type: OrderType = Field(description="Filled by the typed place tool; callers do not send this.")
    limit_price: Decimal | None = Field(
        default=None,
        max_digits=20,
        decimal_places=4,
        description=LIMIT_PRICE_DESC,
    )
    stop_price: Decimal | None = Field(
        default=None,
        max_digits=20,
        decimal_places=4,
        description=STOP_PRICE_DESC,
    )
    time_validity: TimeValidity | None = Field(default=None, description=TIME_VALIDITY_DESC)
    extended_hours: bool = Field(default=False, description=EXTENDED_HOURS_DESC)

    @field_validator("quantity", "limit_price", "stop_price")
    @classmethod
    def _gt_zero(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return value
        return _positive_decimal(value)


class LargeOrderInput(OrderInput):
    rationale: str = Field(min_length=20, max_length=500, description=RATIONALE_DESC)


class EquityOrderFields(BaseModel):
    ticker: str = Field(description=TICKER_DESC)
    side: Side = Field(description=SIDE_DESC)
    quantity: Decimal = Field(max_digits=20, decimal_places=8, description=QUANTITY_DESC)
    extended_hours: bool = Field(default=False, description=EXTENDED_HOURS_DESC)

    @field_validator("quantity", "limit_price", "stop_price", check_fields=False)
    @classmethod
    def _gt_zero(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return value
        return _positive_decimal(value)

    def _base_kwargs(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "quantity": self.quantity,
            "extended_hours": self.extended_hours,
        }


class MarketOrderInput(EquityOrderFields):
    def to_order_input(self) -> OrderInput:
        return OrderInput(**self._base_kwargs(), order_type=OrderType.market)


class LimitOrderInput(EquityOrderFields):
    limit_price: Decimal = Field(max_digits=20, decimal_places=4, description=LIMIT_PRICE_DESC)
    time_validity: TimeValidity = Field(description=TIME_VALIDITY_DESC)

    def to_order_input(self) -> OrderInput:
        return OrderInput(
            **self._base_kwargs(),
            order_type=OrderType.limit,
            limit_price=self.limit_price,
            time_validity=self.time_validity,
        )


class StopOrderInput(EquityOrderFields):
    stop_price: Decimal = Field(max_digits=20, decimal_places=4, description=STOP_PRICE_DESC)
    time_validity: TimeValidity = Field(description=TIME_VALIDITY_DESC)

    def to_order_input(self) -> OrderInput:
        return OrderInput(
            **self._base_kwargs(),
            order_type=OrderType.stop,
            stop_price=self.stop_price,
            time_validity=self.time_validity,
        )


class StopLimitOrderInput(EquityOrderFields):
    limit_price: Decimal = Field(max_digits=20, decimal_places=4, description=LIMIT_PRICE_DESC)
    stop_price: Decimal = Field(max_digits=20, decimal_places=4, description=STOP_PRICE_DESC)
    time_validity: TimeValidity = Field(description=TIME_VALIDITY_DESC)

    def to_order_input(self) -> OrderInput:
        return OrderInput(
            **self._base_kwargs(),
            order_type=OrderType.stop_limit,
            limit_price=self.limit_price,
            stop_price=self.stop_price,
            time_validity=self.time_validity,
        )


def _with_rationale(canonical: OrderInput, rationale: str) -> LargeOrderInput:
    return LargeOrderInput(**canonical.model_dump(), rationale=rationale)


class LargeMarketOrderInput(MarketOrderInput):
    rationale: str = Field(min_length=20, max_length=500, description=RATIONALE_DESC)

    def to_order_input(self) -> LargeOrderInput:
        return _with_rationale(super().to_order_input(), self.rationale)


class LargeLimitOrderInput(LimitOrderInput):
    rationale: str = Field(min_length=20, max_length=500, description=RATIONALE_DESC)

    def to_order_input(self) -> LargeOrderInput:
        return _with_rationale(super().to_order_input(), self.rationale)


class LargeStopOrderInput(StopOrderInput):
    rationale: str = Field(min_length=20, max_length=500, description=RATIONALE_DESC)

    def to_order_input(self) -> LargeOrderInput:
        return _with_rationale(super().to_order_input(), self.rationale)


class LargeStopLimitOrderInput(StopLimitOrderInput):
    rationale: str = Field(min_length=20, max_length=500, description=RATIONALE_DESC)

    def to_order_input(self) -> LargeOrderInput:
        return _with_rationale(super().to_order_input(), self.rationale)


def as_order_input(inputs: Any) -> OrderInput:
    converter = getattr(inputs, "to_order_input", None)
    if callable(converter):
        return converter()
    if isinstance(inputs, OrderInput):
        return inputs
    raise TypeError(f"Cannot convert {type(inputs).__name__} to OrderInput")


TYPED_PLACE_INPUTS = (
    MarketOrderInput,
    LimitOrderInput,
    StopOrderInput,
    StopLimitOrderInput,
    LargeMarketOrderInput,
    LargeLimitOrderInput,
    LargeStopOrderInput,
    LargeStopLimitOrderInput,
)


class CancelOrderInput(BaseModel):
    t212_order_id: str = Field(
        description="Broker order id from get_open_orders or a previous placement. Only orders this BFA placed can be cancelled."
    )


class GetInstrumentsInput(BaseModel):
    ticker: str | None = Field(
        default=None,
        description="Optional Trading 212 ticker. Omit to list the whitelist plus names currently held.",
    )


class GetExchangesInput(BaseModel):
    working_schedule_id: str | None = Field(
        default=None,
        description="Optional schedule id from get_instruments.working_schedule_id.",
    )


class InstrumentView(BaseModel):
    ticker: str
    name: str | None = None
    isin: str | None = None
    type: str | None = None
    currency: str | None = None
    extended_hours: bool = False
    max_open_quantity: Decimal | None = None
    quantity_step: Decimal
    broker_last: Decimal | None = None
    fx_czk_per_unit: Decimal | None = None
    working_schedule_id: str | None = None
    on_whitelist: bool


class InstrumentsOutput(BaseModel):
    instruments: list[InstrumentView]


class ExchangeEvent(BaseModel):
    type: str | None = None
    date: str | None = None
    time: str | None = None


class ExchangeView(BaseModel):
    working_schedule_id: str | None = None
    name: str | None = None
    timezone: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class ExchangesOutput(BaseModel):
    exchanges: list[ExchangeView]


class AccountSummaryOutput(BaseModel):
    cash_available_czk: Decimal
    invested_czk: Decimal
    total_equity_czk: Decimal
    currency: str = "CZK"


class PositionView(BaseModel):
    ticker: str
    quantity: Decimal
    average_price: Decimal | None = None
    last_price: Decimal | None = None
    quote_source: str | None = None
    market_value_czk: Decimal | None = None
    unrealized_pl: Decimal | None = None


class PortfolioOutput(BaseModel):
    positions: list[PositionView]
    position_count: int
    max_positions: int


class OpenOrderView(BaseModel):
    t212_order_id: str
    ticker: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_validity: TimeValidity | None = None
    created_at: datetime | None = None
    tracked_by_host: bool


class OpenOrdersOutput(BaseModel):
    orders: list[OpenOrderView]


class WhitelistOutput(BaseModel):
    tickers: list[str]
    max_names: int
    approval_notional_czk: Decimal
    environment: str


class SourcedValue(BaseModel):
    source: str
    data: Any = None


class TitleResearchOutput(BaseModel):
    ticker: str
    quote: SourcedValue | None = None
    history: list[SourcedValue] = Field(default_factory=list)
    profile: SourcedValue | None = None
    metrics: SourcedValue | None = None
    news: list[SourcedValue] = Field(default_factory=list)
    earnings: list[SourcedValue] = Field(default_factory=list)
    macro: list[SourcedValue] = Field(default_factory=list)
    filings: list[SourcedValue] = Field(default_factory=list)


class TradeIntentView(BaseModel):
    intent_id: UUID
    status: str
    ticker: str
    side: str
    order_type: str
    quantity: Decimal
    notional_czk: Decimal | None = None
    submitted_at: datetime | None = None
    t212_order_id: str | None = None
    error_code: str | None = None
    broker_message: str | None = None


class TradeIntentsOutput(BaseModel):
    intents: list[TradeIntentView]


class FxBlock(BaseModel):
    fx_czk_per_unit: Decimal
    fx_date: date
    fx_source: str


class ReviewPortfolioOutput(BaseModel):
    portfolio: PortfolioOutput
    open_intents: list[TradeIntentView]
    whitelist: WhitelistOutput
    fx: FxBlock | None = None
    research: list[TitleResearchOutput] = Field(default_factory=list)


class OrderOutput(BaseModel):
    intent_id: UUID | None = None
    status: str
    t212_order_id: str | None = None
    ticker: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_validity: TimeValidity | None = None
    notional_czk: Decimal | None = None
    fx_czk_per_unit: Decimal | None = None
    fx_date: date | None = None
    fx_source: str | None = None
    quote_source: str | None = None
    environment: str
    error_code: str | None = None


class CancelOrderOutput(BaseModel):
    t212_order_id: str
    cancelled: bool
    error_code: str | None = None
