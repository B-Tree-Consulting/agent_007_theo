"""Shared Action base, guards, and plan steps for equity orders."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from agentstepkit import Action, ApprovalsPolicy, PlanBuilder, assert_that, effect, gather_fact
from agentstepkit.core import AssertionResult, ConfirmResult, ConfirmStatus, ExecuteResult, Invariant
from pydantic import BaseModel

from src.shared.invoke_scope import (
    get_invoke_approval_record_id,
    get_invoke_case_id,
    get_invoke_correlation_id,
)
from src.theo.book import (
    assert_stop_side,
    held_tickers,
    missing_order_fields,
    notional_price,
    working_buy_new_names,
    working_sell_quantity,
)
from src.theo.clients.t212 import get_t212_client
from src.theo.comments import (
    render_approval_comment,
    render_cancelled_comment,
    render_compensation_fill_comment,
    render_placed_comment,
)
from src.theo.errors import (
    APPROVAL_REQUIRED,
    BELOW_APPROVAL_THRESHOLD,
    BROKER_AMBIGUOUS,
    BROKER_REJECTED,
    COMPENSATION_PARTIAL,
    FX_UNAVAILABLE,
    INSUFFICIENT_CASH,
    LARGE_PROPOSAL_PENDING,
    ORDER_NOT_TRACKED,
    POSITION_CAP,
    QUOTE_UNAVAILABLE,
    REQUEST_ID_REUSED,
    SHORT_REJECTED,
    STOP_PRICE_INVALID,
    TOOL_VERSION,
    VALIDATION_ERROR,
    WHITELIST_EMPTY,
    WHITELIST_REJECTED,
    TheoError,
)
from src.theo.schemas import (
    CancelOrderInput,
    LargeLimitOrderInput,
    LargeMarketOrderInput,
    LargeOrderInput,
    LargeStopLimitOrderInput,
    LargeStopOrderInput,
    LimitOrderInput,
    MarketOrderInput,
    OrderInput,
    OrderOutput,
    ReviewPortfolioInput,
    Side,
    StopLimitOrderInput,
    StopOrderInput,
    as_order_input,
)
from src.theo.snapshot import BookSnapshot, load_order_snapshot
from src.theo.stores import intents as intent_store

AUTO_POLICY = ApprovalsPolicy(max_write_steps_auto=4, max_systems_auto=2, min_risk_for_auto="low")

PLACE_TOOL_TWINS = {
    "place_market_equity_order": "place_large_market_equity_order",
    "place_limit_equity_order": "place_large_limit_equity_order",
    "place_stop_equity_order": "place_large_stop_equity_order",
    "place_stop_limit_equity_order": "place_large_stop_limit_equity_order",
}
PLACE_TOOL_TWINS.update({high: low for low, high in list(PLACE_TOOL_TWINS.items())})


class InvokeScope:
    def __init__(self) -> None:
        self.case_id: str | None = None


class OrderFacts(BaseModel):
    book: Any = None
    correlation_conflict: bool = False


class CaseComments:
    async def add_comment(self, *, case_id: str, body: str) -> None:  # pragma: no cover - protocol
        raise NotImplementedError


def _fail(code: str, message: str) -> tuple[bool, str]:
    return False, f"{code}: {message}"


def _book(facts: Any, guard_facts: dict | None) -> BookSnapshot | None:
    if isinstance(facts, dict):
        return facts.get("book")
    if guard_facts:
        return guard_facts.get("book")
    return getattr(facts, "book", None)


def _canonical(inputs: Any) -> OrderInput:
    return as_order_input(inputs)


def _action_name(ctx: Any) -> str:
    return str(getattr(getattr(ctx, "action", None), "name", "") or "")


def check_payload(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx, facts, guard_facts
    missing = missing_order_fields(_canonical(inputs))
    if missing:
        return _fail(VALIDATION_ERROR, "Missing required fields: " + ", ".join(missing))
    return True


def check_replay(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    book = _book(facts, guard_facts)
    existing = getattr(book, "existing_intent", None) if book else None
    if existing is None:
        return True
    digest = intent_store.payload_hash(_canonical(inputs))
    if existing.payload_hash != digest:
        if existing.status in intent_store.TERMINAL_STATUSES:
            return _fail(REQUEST_ID_REUSED, "This order was already sent and cannot be replaced")
        return True
    if existing.status == "failed" and existing.error_code:
        return _fail(existing.error_code, existing.broker_message or existing.error_code)
    return True


def check_whitelist(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx
    order = _canonical(inputs)
    if order.side != Side.buy:
        return True
    book = _book(facts, guard_facts)
    if book is None:
        return True
    if not book.whitelist:
        return _fail(WHITELIST_EMPTY, "The buy whitelist is empty")
    if order.ticker not in book.whitelist:
        return _fail(WHITELIST_REJECTED, f"{order.ticker} is not on the whitelist")
    return True


def check_fx(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del inputs, ctx
    book = _book(facts, guard_facts)
    if book is None or book.fx_czk_per_unit is None:
        return _fail(FX_UNAVAILABLE, "No CNB fixing is available")
    return True


def check_quote(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx
    book = _book(facts, guard_facts)
    price = notional_price(_canonical(inputs), book.last_price if book else None)
    if price is None:
        return _fail(QUOTE_UNAVAILABLE, "No last price is available for this ticker")
    return True


def check_stop(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx
    order = _canonical(inputs)
    if order.stop_price is None:
        return True
    book = _book(facts, guard_facts)
    if book is None or book.last_price is None:
        return _fail(QUOTE_UNAVAILABLE, "No last price is available to check the stop")
    try:
        assert_stop_side(order, book.last_price)
    except TheoError as exc:
        return _fail(exc.code, exc.message)
    return True


def check_gate_low(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    book = _book(facts, guard_facts)
    if book is None:
        return True
    notional = book.notional_for(_canonical(inputs))
    if notional is not None and notional > book.attention_notional:
        twin = PLACE_TOOL_TWINS.get(_action_name(ctx), "place_large_market_equity_order")
        return _fail(
            APPROVAL_REQUIRED,
            f"Use {twin}; this trade is above the approval threshold",
        )
    return True


def check_gate_high(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    book = _book(facts, guard_facts)
    if book is None:
        return True
    notional = book.notional_for(_canonical(inputs))
    if notional is not None and notional <= book.attention_notional:
        twin = PLACE_TOOL_TWINS.get(_action_name(ctx), "place_market_equity_order")
        return _fail(
            BELOW_APPROVAL_THRESHOLD,
            f"Use {twin}; this trade is at or under the approval threshold",
        )
    return True


def check_short(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx
    order = _canonical(inputs)
    if order.side != Side.sell:
        return True
    book = _book(facts, guard_facts)
    if book is None:
        return True
    held = next((p["quantity"] for p in book.positions if p.get("ticker") == order.ticker), Decimal("0"))
    working = working_sell_quantity(book.orders, order.ticker)
    if order.quantity > held - working:
        return _fail(SHORT_REJECTED, "Sell quantity exceeds the open long minus working sells")
    return True


def check_cap(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx
    order = _canonical(inputs)
    if order.side != Side.buy:
        return True
    book = _book(facts, guard_facts)
    if book is None:
        return True
    held = held_tickers(book.positions)
    if order.ticker in held:
        return True
    names = held | working_buy_new_names(book.orders, held) | {order.ticker}
    if len(names) > book.max_positions:
        return _fail(POSITION_CAP, f"The book already holds the maximum of {book.max_positions} names")
    return True


def check_large_pending(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx, inputs
    book = _book(facts, guard_facts)
    pending = getattr(book, "pending_same_ticker", None) if book else None
    if pending is not None:
        return _fail(LARGE_PROPOSAL_PENDING, "A large proposal for this ticker is still undecided")
    return True


def check_quantity_step(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx
    book = _book(facts, guard_facts)
    step = getattr(book, "quantity_step", None) if book else None
    if step is None:
        return True
    order = _canonical(inputs)
    if order.quantity % Decimal(step) != 0:
        return _fail(VALIDATION_ERROR, "quantity must be a multiple of quantity_step")
    return True


def check_cash(inputs: OrderInput, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx
    order = _canonical(inputs)
    if order.side != Side.buy:
        return True
    book = _book(facts, guard_facts)
    if book is None:
        return True
    notional = book.notional_for(order)
    if notional is not None and notional > book.cash_free:
        return _fail(INSUFFICIENT_CASH, "Available cash does not cover this buy")
    return True


class OrderActionBase(Action[OrderInput, OrderFacts]):
    version = TOOL_VERSION
    input_model = OrderInput
    approvals_policy = AUTO_POLICY
    gate: Literal["low", "high"] = "low"

    def __init__(self, comments: Any, scope: InvokeScope | None = None) -> None:
        super().__init__()
        self.comments = comments
        self.scope = scope or InvokeScope()
        self._dependencies = {"comments": comments, "scope": self.scope, "action": self}

    async def submit(self, inputs: OrderInput, mode: str = "auto", **kwargs: Any):
        self.scope.case_id = kwargs.get("case_id") or get_invoke_case_id()
        result = await super().submit(inputs, mode=mode, **kwargs)
        token = getattr(result, "plan_token", None)
        if token:
            row = self._intent(inputs)
            if row is not None:
                intent_store.set_plan_token(row.id, token)
        return result

    async def confirm(self, plan_token: str, inputs: OrderInput, **kwargs: Any):
        self.scope.case_id = kwargs.get("case_id") or get_invoke_case_id()
        case_id = self.scope.case_id
        order = _canonical(inputs)
        row = intent_store.get_by_plan_token(case_id, plan_token) if case_id and plan_token else None
        if row is None:
            row = self._intent(order)
        if row is not None and row.payload_hash != intent_store.payload_hash(order):
            row = None
        if row is not None and row.status == "executed" and row.t212_order_id:
            return self._confirm_replay(row)
        if row is None or row.status != "awaiting_approval":
            return self._confirm_rejected()
        approval_id = get_invoke_approval_record_id()
        if approval_id:
            intent_store.set_approval_record(row.id, approval_id)
            row.approval_record_id = approval_id[:128]
        self._bound_intent = row
        try:
            return await super().confirm(plan_token, inputs, **kwargs)
        finally:
            self._bound_intent = None

    def _confirm_replay(self, row: Any) -> ConfirmResult:
        result = ExecuteResult(
            status="succeeded",
            correlation_id=self._correlation() or "confirm",
            trace=[],
            assertions=[],
            outputs={"intent_id": str(row.id), "status": "executed", "t212_order_id": row.t212_order_id},
        )
        return ConfirmResult(status=ConfirmStatus.SUCCEEDED, result=result)

    def _confirm_rejected(self) -> ConfirmResult:
        result = ExecuteResult(
            status="failed",
            correlation_id=self._correlation() or "confirm",
            trace=[],
            assertions=[
                AssertionResult(
                    id=VALIDATION_ERROR,
                    kind="pre",
                    severity="blocker",
                    status="failed",
                    evidence="No open proposal matches this confirm",
                )
            ],
            outputs={},
        )
        return ConfirmResult(status=ConfirmStatus.FAILED, reason="preconditions_failed", result=result)

    async def snapshot(self, inputs: OrderInput) -> BookSnapshot:
        case_id = self.scope.case_id or get_invoke_case_id()
        if not case_id:
            raise TheoError(VALIDATION_ERROR, "case_id is required")
        return await load_order_snapshot(case_id, _canonical(inputs), tool_name=self.name)

    async def preflight(self, inputs: OrderInput) -> OrderFacts:
        book = self._guard_facts.get("book") if self._guard_facts else None
        if book is None:
            book = await self.snapshot(inputs)
        return OrderFacts(book=book)

    async def invariants(self, inputs: OrderInput, facts: OrderFacts):
        del inputs
        if not facts.correlation_conflict:
            return []
        return [
            Invariant(
                id=REQUEST_ID_REUSED,
                kind="pre",
                severity="blocker",
                description="This order was already sent and cannot be replaced",
                check=lambda: (False, "This order was already sent and cannot be replaced"),
            )
        ]

    def _correlation(self) -> str | None:
        return intent_store.clean_correlation(get_invoke_correlation_id())

    def _persist(self, inputs: OrderInput, status: str, book: Any) -> intent_store.IntentWrite:
        case_id = self.scope.case_id or get_invoke_case_id()
        if not case_id:
            raise TheoError(VALIDATION_ERROR, "case_id is required")
        order = _canonical(inputs)
        return intent_store.upsert_intent(
            case_id=case_id,
            inputs=order,
            status=status,
            tool_name=self.name,
            correlation_id=self._correlation(),
            notional_price=notional_price(order, book.last_price if book else None),
            notional_czk=book.notional_for(order) if book else None,
            quote_source=book.quote_source if book else None,
            fx_czk_per_unit=book.fx_czk_per_unit if book else None,
            fx_date=book.fx_date if book else None,
            fx_source=book.fx_source if book else None,
            rationale=getattr(order, "rationale", None),
        )

    def _intent(self, inputs: OrderInput):
        bound = getattr(self, "_bound_intent", None)
        if bound is not None:
            return bound
        case_id = self.scope.case_id or get_invoke_case_id()
        correlation = self._correlation()
        if not case_id or not correlation:
            return None
        row = intent_store.get_active(case_id, correlation, self.name)
        if row is None:
            return None
        if row.payload_hash != intent_store.payload_hash(_canonical(inputs)) and row.status in intent_store.REPLACEABLE_STATUSES:
            return None
        return row

    def _ensure_dispatching_row(self, inputs: OrderInput):
        row = self._intent(inputs)
        case_id = self.scope.case_id or get_invoke_case_id()
        book = self._guard_facts.get("book") if self._guard_facts else None
        created_now = False
        if row is None and case_id:
            written = self._persist(inputs, "dispatching", book)
            if written.conflict:
                raise TheoError(REQUEST_ID_REUSED, "This order was already sent and cannot be replaced")
            row = written.row
            created_now = True
        if row is None:
            raise TheoError(VALIDATION_ERROR, "Intent row is missing")
        if row.status == "executed" and row.t212_order_id:
            return row
        if created_now:
            self._fresh_dispatch = True
            return row
        intent_store.mark_status(row.id, "dispatching", confirmed=True)
        return self._intent(inputs) or row

    @effect(
        describe="POST the matching Trading 212 equity order and store the broker id",
        systems=("T212",),
        compensate="cancel_pending_order",
    )
    async def post_broker_order(self, inputs: OrderInput) -> str:
        row = self._ensure_dispatching_row(inputs)
        if row.t212_order_id:
            return row.t212_order_id
        fresh = getattr(self, "_fresh_dispatch", False)
        self._fresh_dispatch = False
        order = _canonical(inputs)
        if not fresh and row.status == "dispatching" and row.t212_order_id is None:
            adopted = await _reconcile_dispatch(order, row)
            if adopted:
                return adopted
            intent_store.mark_status(row.id, "failed", error_code=BROKER_AMBIGUOUS)
            raise TheoError(
                BROKER_AMBIGUOUS,
                "A previous send may already be at the broker and could not be matched",
            )
        try:
            order_id = await get_t212_client().place_order(order)
        except TheoError as exc:
            intent_store.mark_status(row.id, "failed", error_code=exc.code, broker_message=exc.message)
            raise
        intent_store.mark_status(row.id, "executed", t212_order_id=order_id)
        return order_id

    async def cancel_pending_order(self, inputs: OrderInput) -> None:
        row = self._intent(inputs)
        if row is None:
            return
        if not row.t212_order_id:
            if row.status != "executed":
                intent_store.mark_status(row.id, "failed", error_code=BROKER_REJECTED)
            return
        try:
            await get_t212_client().cancel_order(row.t212_order_id)
            intent_store.mark_status(row.id, "failed", error_code=BROKER_REJECTED)
        except TheoError:
            intent_store.mark_status(row.id, "executed", error_code=COMPENSATION_PARTIAL)

    @effect(describe="Record the placed order as a case comment", systems=("CMS",))
    async def comment_placed(self, inputs: OrderInput) -> None:
        row = self._intent(inputs)
        case_id = self.scope.case_id or get_invoke_case_id()
        if not case_id:
            return
        from src.theo.clients.t212 import current_t212_environment

        order = _canonical(inputs)
        body = render_placed_comment(
            ticker=order.ticker,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            notional_czk=row.notional_czk if row else None,
            fx_date=row.fx_date if row else None,
            fx_czk_per_unit=row.fx_czk_per_unit if row else None,
            t212_order_id=row.t212_order_id if row else None,
            environment=current_t212_environment(),
        )
        if row and row.error_code == COMPENSATION_PARTIAL and row.t212_order_id:
            body = body + " " + render_compensation_fill_comment(t212_order_id=row.t212_order_id)
        await self.comments.add_comment(case_id=case_id, body=body)

    @effect(describe="Record that the manager approved this large trade", systems=("CMS",))
    async def comment_approved(self, inputs: LargeOrderInput) -> None:
        case_id = self.scope.case_id or get_invoke_case_id()
        if not case_id:
            return
        row = self._intent(inputs)
        waited = None
        if row and row.submitted_at:
            submitted = row.submitted_at
            if submitted.tzinfo is None:
                submitted = submitted.replace(tzinfo=timezone.utc)
            waited = int((datetime.now(timezone.utc) - submitted).total_seconds() // 60)
        body = render_approval_comment(
            rationale=getattr(inputs, "rationale", ""),
            waited_minutes=waited,
            approval_record_id=row.approval_record_id if row else None,
        )
        await self.comments.add_comment(case_id=case_id, body=body)

    async def build_plan(self, inputs: OrderInput, facts: OrderFacts):
        plan = PlanBuilder()
        existing = facts.book.existing_intent if facts.book else None
        if existing is not None and existing.status == "executed" and existing.t212_order_id:
            plan.step(self.comment_placed, inputs=inputs, risk="low")
            return plan.to_list()
        if facts.book is not None:
            facts.book.existing_intent = None
            facts.book.pending_same_ticker = None
        if self.gate == "high":
            written = self._persist(_canonical(inputs), "awaiting_approval", facts.book)
            if written.conflict:
                facts.correlation_conflict = True
                return []
        if self.gate == "high":
            plan.step(self.comment_approved, inputs=inputs, risk="low")
        plan.step(self.post_broker_order, inputs=inputs, risk="low")
        plan.step(self.comment_placed, inputs=inputs, risk="low")
        return plan.to_list()


async def _reconcile_dispatch(inputs: OrderInput, row: Any) -> str | None:
    client = get_t212_client()
    pending = await client.open_orders()
    history = await client.historical_orders()
    matches = []
    from src.theo.book import signed_quantity

    want = signed_quantity(inputs.side, inputs.quantity)
    window_start = row.submitted_at
    for order in pending + history:
        if order.get("ticker") != inputs.ticker:
            continue
        if order.get("signed_quantity") != want:
            continue
        created = order.get("created_at")
        if window_start and created and abs((created - window_start).total_seconds()) > 120:
            continue
        matches.append(order)
    if len(matches) > 1:
        intent_store.mark_status(row.id, "failed", error_code=BROKER_AMBIGUOUS)
        raise TheoError(BROKER_AMBIGUOUS, "More than one matching broker order was found")
    if len(matches) == 1:
        order_id = matches[0]["t212_order_id"]
        intent_store.mark_status(row.id, "executed", t212_order_id=order_id)
        return order_id
    return None


def _apply_order_guards(cls: type, gate: Literal["low", "high"]) -> type:
    cls = gather_fact("book", fetch=lambda inputs, ctx: ctx.action.snapshot(inputs))(cls)
    cls = assert_that.pre(VALIDATION_ERROR, "Order payload must be complete for the order type", check=check_payload)(cls)
    cls = assert_that.pre(REQUEST_ID_REUSED, "request_id cannot be reused for a different order", check=check_replay)(cls)
    cls = assert_that.pre(WHITELIST_REJECTED, "Buys must use a whitelist ticker", check=check_whitelist)(cls)
    cls = assert_that.pre(FX_UNAVAILABLE, "A CNB CZK fixing must be available", check=check_fx)(cls)
    cls = assert_that.pre(QUOTE_UNAVAILABLE, "A market price is required", check=check_quote)(cls)
    cls = assert_that.pre(STOP_PRICE_INVALID, "Stop price must sit on the correct side of the last price", check=check_stop)(cls)
    cls = assert_that.pre(VALIDATION_ERROR, "quantity must be a multiple of quantity_step", check=check_quantity_step)(cls)
    if gate == "low":
        cls = assert_that.pre(APPROVAL_REQUIRED, "Large trades must use the matching place_large_* tool", check=check_gate_low)(cls)
        cls = assert_that.pre(
            LARGE_PROPOSAL_PENDING,
            "A low-risk order cannot be placed while a large proposal for this ticker is undecided",
            check=check_large_pending,
        )(cls)
    else:
        cls = assert_that.pre(BELOW_APPROVAL_THRESHOLD, "Small trades must use the matching low-risk place tool", check=check_gate_high)(cls)
    cls = assert_that.pre(SHORT_REJECTED, "Sells cannot exceed the open long", check=check_short)(cls)
    cls = assert_that.pre(POSITION_CAP, "The book cannot exceed the name cap", check=check_cap)(cls)
    cls = assert_that.pre(INSUFFICIENT_CASH, "Buys must be covered by available cash", check=check_cash)(cls)
    return cls


def _make_place_action(name: str, input_model: type, gate: Literal["low", "high"]) -> type:
    class_name = "".join(part.capitalize() for part in name.split("_"))

    class PlaceTypedOrder(OrderActionBase):
        pass

    PlaceTypedOrder.__name__ = class_name
    PlaceTypedOrder.__qualname__ = class_name
    PlaceTypedOrder.name = name
    PlaceTypedOrder.input_model = input_model
    PlaceTypedOrder.gate = gate
    return _apply_order_guards(PlaceTypedOrder, gate)


PLACE_ACTION_SPECS: list[tuple[str, type, Literal["low", "high"]]] = [
    ("place_market_equity_order", MarketOrderInput, "low"),
    ("place_limit_equity_order", LimitOrderInput, "low"),
    ("place_stop_equity_order", StopOrderInput, "low"),
    ("place_stop_limit_equity_order", StopLimitOrderInput, "low"),
    ("place_large_market_equity_order", LargeMarketOrderInput, "high"),
    ("place_large_limit_equity_order", LargeLimitOrderInput, "high"),
    ("place_large_stop_equity_order", LargeStopOrderInput, "high"),
    ("place_large_stop_limit_equity_order", LargeStopLimitOrderInput, "high"),
]

PLACE_ACTIONS = {
    name: _make_place_action(name, model, gate) for name, model, gate in PLACE_ACTION_SPECS
}
PlaceMarketEquityOrder = PLACE_ACTIONS["place_market_equity_order"]
PlaceLimitEquityOrder = PLACE_ACTIONS["place_limit_equity_order"]
PlaceStopEquityOrder = PLACE_ACTIONS["place_stop_equity_order"]
PlaceStopLimitEquityOrder = PLACE_ACTIONS["place_stop_limit_equity_order"]
PlaceLargeMarketEquityOrder = PLACE_ACTIONS["place_large_market_equity_order"]
PlaceLargeLimitEquityOrder = PLACE_ACTIONS["place_large_limit_equity_order"]
PlaceLargeStopEquityOrder = PLACE_ACTIONS["place_large_stop_equity_order"]
PlaceLargeStopLimitEquityOrder = PLACE_ACTIONS["place_large_stop_limit_equity_order"]


class ReviewFacts(BaseModel):
    lines: list[str] = []
    fx_date: Any = None
    missing: list[str] = []
    output: dict = {}
    broker_error: str | None = None


class ReviewPortfolio(Action):
    name = "review_portfolio"
    version = TOOL_VERSION
    input_model = ReviewPortfolioInput
    approvals_policy = AUTO_POLICY

    def __init__(self, comments: Any, scope: InvokeScope | None = None) -> None:
        super().__init__()
        self.comments = comments
        self.scope = scope or InvokeScope()
        self._dependencies = {"comments": comments, "scope": self.scope}

    async def submit(self, inputs: Any, mode: str = "auto", **kwargs: Any):
        self.scope.case_id = kwargs.get("case_id") or get_invoke_case_id()
        return await super().submit(inputs, mode=mode, **kwargs)

    async def preflight(self, inputs: Any) -> ReviewFacts:
        from src.theo.queries import portfolio_from_snapshot
        from src.theo.schemas import ReviewPortfolioOutput, TradeIntentView, WhitelistOutput
        from src.theo.settings import attention_notional, parse_whitelist
        from src.theo.snapshot import load_account_snapshot
        from src.config import get_settings
        from src.theo.clients.market_data import get_market_data_client
        from src.theo.clients.t212 import current_t212_environment

        try:
            snap = await load_account_snapshot()
        except TheoError as exc:
            return ReviewFacts(broker_error=exc.message)
        portfolio = portfolio_from_snapshot(snap)
        case_id = self.scope.case_id or get_invoke_case_id()
        open_intents = []
        if case_id:
            open_intents = [
                TradeIntentView(
                    intent_id=row.id,
                    status=row.status,
                    ticker=row.ticker,
                    side=row.side,
                    order_type=row.order_type,
                    quantity=row.quantity,
                    notional_czk=row.notional_czk,
                    submitted_at=row.submitted_at,
                    t212_order_id=row.t212_order_id,
                    error_code=row.error_code,
                )
                for row in intent_store.list_for_case(case_id, limit=50)
            ]
        settings = get_settings()
        whitelist = WhitelistOutput(
            tickers=list(parse_whitelist(settings)),
            max_names=settings.theo_max_positions,
            approval_notional_czk=attention_notional(settings),
            environment=current_t212_environment(),
        )
        research = []
        missing: list[str] = []
        if getattr(inputs, "include_research", True):
            names = {p.ticker for p in portfolio.positions} | set(whitelist.tickers)
            for ticker in sorted(names):
                mark = next((p.last_price for p in portfolio.positions if p.ticker == ticker), None)
                pack = await get_market_data_client().research(ticker, position_mark=mark)
                research.append(pack)
                if pack.quote is None:
                    missing.append(ticker)
        lines = [
            f"{p.ticker}: mark {p.last_price} source {p.quote_source} value {p.market_value_czk}"
            for p in portfolio.positions
        ]
        fx = None
        if snap.fx_czk_per_unit is not None and snap.fx_date is not None:
            from src.theo.schemas import FxBlock

            fx = FxBlock(
                fx_czk_per_unit=snap.fx_czk_per_unit,
                fx_date=snap.fx_date,
                fx_source=snap.fx_source or "CNB",
            )
        output = ReviewPortfolioOutput(
            portfolio=portfolio,
            open_intents=open_intents,
            whitelist=whitelist,
            fx=fx,
            research=research,
        ).model_dump(mode="json")
        return ReviewFacts(lines=lines or ["(no positions)"], fx_date=snap.fx_date, missing=missing, output=output)

    async def invariants(self, inputs: Any, facts: ReviewFacts):
        del inputs
        if not facts.broker_error:
            return []
        message = facts.broker_error
        return [
            Invariant(
                id=BROKER_REJECTED,
                kind="pre",
                severity="blocker",
                description="The broker must answer before a review can be recorded",
                check=lambda: (False, message),
            )
        ]

    async def build_plan(self, inputs: Any, facts: ReviewFacts):
        plan = PlanBuilder()
        plan.step(
            self.comment_review,
            lines=facts.lines,
            fx_date=facts.fx_date,
            missing=facts.missing,
            risk="low",
        )
        return plan.to_list()

    @effect(describe="Record the portfolio review as a case comment", systems=("CMS",))
    async def comment_review(self, lines: list[str], fx_date: Any, missing: list[str]) -> dict:
        from src.theo.comments import render_review_comment

        case_id = self.scope.case_id or get_invoke_case_id()
        if case_id:
            await self.comments.add_comment(
                case_id=case_id,
                body=render_review_comment(lines, fx_date=fx_date, missing=missing),
            )
        return {"status": "reviewed"}


class CancelFacts(BaseModel):
    tracked: bool = False
    ticker: str = ""
    side: str = ""
    quantity: Decimal = Decimal("0")


class CancelEquityOrder(Action):
    name = "cancel_equity_order"
    version = TOOL_VERSION
    input_model = CancelOrderInput
    approvals_policy = AUTO_POLICY

    def __init__(self, comments: Any, scope: InvokeScope | None = None) -> None:
        super().__init__()
        self.comments = comments
        self.scope = scope or InvokeScope()
        self._dependencies = {"comments": comments, "scope": self.scope, "action": self}

    async def submit(self, inputs: Any, mode: str = "auto", **kwargs: Any):
        self.scope.case_id = kwargs.get("case_id") or get_invoke_case_id()
        return await super().submit(inputs, mode=mode, **kwargs)

    async def snapshot_cancel(self, inputs: Any) -> CancelFacts:
        row = intent_store.get_by_broker_id(inputs.t212_order_id)
        if row is None:
            return CancelFacts(tracked=False)
        return CancelFacts(
            tracked=True,
            ticker=row.ticker,
            side=row.side,
            quantity=row.quantity,
        )

    async def preflight(self, inputs: Any) -> CancelFacts:
        facts = self._guard_facts.get("cancel") if self._guard_facts else None
        return facts or await self.snapshot_cancel(inputs)

    async def invariants(self, inputs: Any, facts: CancelFacts):
        del inputs, facts
        return []

    async def build_plan(self, inputs: Any, facts: CancelFacts):
        plan = PlanBuilder()
        row = intent_store.get_by_broker_id(inputs.t212_order_id)
        if row is not None and row.status == "cancelled":
            plan.step(self.replay_cancelled, t212_order_id=inputs.t212_order_id, risk="low")
            return plan.to_list()
        plan.step(self.delete_broker_order, t212_order_id=inputs.t212_order_id, risk="low")
        plan.step(
            self.comment_cancelled,
            t212_order_id=inputs.t212_order_id,
            ticker=facts.ticker,
            side=facts.side,
            quantity=facts.quantity,
            risk="low",
        )
        return plan.to_list()

    @effect(describe="Return the stored cancellation without calling the broker again", systems=())
    async def replay_cancelled(self, t212_order_id: str) -> dict:
        return {"t212_order_id": t212_order_id, "cancelled": True, "error_code": None}

    @effect(describe="DELETE the working order at Trading 212", systems=("T212",))
    async def delete_broker_order(self, t212_order_id: str) -> None:
        row = intent_store.get_by_broker_id(t212_order_id)
        if row is not None and row.status == "cancelled":
            return
        await get_t212_client().cancel_order(t212_order_id)
        row = intent_store.get_by_broker_id(t212_order_id)
        if row is not None:
            intent_store.mark_status(row.id, "cancelled")

    @effect(describe="Record the cancellation as a case comment", systems=("CMS",))
    async def comment_cancelled(self, t212_order_id: str, ticker: str, side: str, quantity: Decimal) -> dict:
        case_id = self.scope.case_id or get_invoke_case_id()
        if case_id:
            await self.comments.add_comment(
                case_id=case_id,
                body=render_cancelled_comment(
                    t212_order_id=t212_order_id,
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                ),
            )
        return {"t212_order_id": t212_order_id, "cancelled": True, "error_code": None}


def _check_tracked(inputs: Any, ctx: Any, facts: Any, guard_facts: dict) -> tuple[bool, str] | bool:
    del ctx, inputs
    data = facts if isinstance(facts, dict) else guard_facts
    cancel = data.get("cancel") if isinstance(data, dict) else getattr(facts, "tracked", None)
    tracked = False
    if hasattr(cancel, "tracked"):
        tracked = cancel.tracked
    elif isinstance(cancel, dict):
        tracked = bool(cancel.get("tracked"))
    if not tracked:
        from src.theo.errors import ORDER_NOT_TRACKED as CODE

        return False, f"{CODE}: Only orders this BFA placed can be cancelled"
    return True


CancelEquityOrder = gather_fact("cancel", fetch=lambda inputs, ctx: ctx.action.snapshot_cancel(inputs))(
    CancelEquityOrder
)
CancelEquityOrder = assert_that.pre(
    ORDER_NOT_TRACKED,
    "Only orders this BFA placed can be cancelled",
    check=_check_tracked,
)(CancelEquityOrder)

