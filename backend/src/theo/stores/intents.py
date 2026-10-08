"""Persistence for equity_order_intents."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.db.session import SessionLocal, get_engine
from src.theo.models import EquityOrderIntent
from src.theo.schemas import OrderInput
from src.theo.settings import intent_ttl

TERMINAL_STATUSES = frozenset({"dispatching", "executed", "cancelled"})
REPLACEABLE_STATUSES = frozenset({"failed", "awaiting_approval"})
_CORRELATION_LEN = 256


def _session():
    return SessionLocal(bind=get_engine())


class IntentWrite:
    def __init__(self, row: EquityOrderIntent, *, conflict: bool = False) -> None:
        self.row = row
        self.conflict = conflict


def clean_correlation(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    return stripped[:_CORRELATION_LEN]


def payload_hash(inputs: OrderInput) -> str:
    payload = {
        "ticker": inputs.ticker,
        "side": inputs.side.value,
        "quantity": str(inputs.quantity),
        "order_type": inputs.order_type.value,
        "limit_price": str(inputs.limit_price) if inputs.limit_price is not None else None,
        "stop_price": str(inputs.stop_price) if inputs.stop_price is not None else None,
        "time_validity": inputs.time_validity.value if inputs.time_validity else None,
        "extended_hours": inputs.extended_hours,
    }
    rationale = getattr(inputs, "rationale", None)
    if rationale:
        payload["rationale"] = rationale
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _active_stmt(case_id: str, correlation_id: str, tool_name: str):
    return select(EquityOrderIntent).where(
        EquityOrderIntent.case_id == case_id,
        EquityOrderIntent.correlation_id == correlation_id,
        EquityOrderIntent.tool_name == tool_name,
        EquityOrderIntent.status != "abandoned",
    )


def get_active(case_id: str, correlation_id: str, tool_name: str) -> EquityOrderIntent | None:
    session = _session()
    try:
        return session.scalar(_active_stmt(case_id, correlation_id, tool_name))
    finally:
        session.close()


def get_by_plan_token(case_id: str, plan_token: str) -> EquityOrderIntent | None:
    session = _session()
    try:
        return session.scalar(
            select(EquityOrderIntent).where(
                EquityOrderIntent.case_id == case_id,
                EquityOrderIntent.plan_token_ref == plan_token,
                EquityOrderIntent.status != "abandoned",
            )
        )
    finally:
        session.close()


def set_approval_record(intent_id: UUID, approval_record_id: str) -> None:
    session = _session()
    try:
        row = session.get(EquityOrderIntent, intent_id)
        if row is None:
            return
        row.approval_record_id = approval_record_id[:128]
        session.commit()
    finally:
        session.close()


def set_plan_token(intent_id: UUID, plan_token: str) -> None:
    session = _session()
    try:
        row = session.get(EquityOrderIntent, intent_id)
        if row is None:
            return
        row.plan_token_ref = plan_token
        session.commit()
    finally:
        session.close()


def get_by_broker_id(t212_order_id: str) -> EquityOrderIntent | None:
    session = _session()
    try:
        return session.scalar(
            select(EquityOrderIntent).where(EquityOrderIntent.t212_order_id == t212_order_id)
        )
    finally:
        session.close()


def pending_for_ticker(case_id: str, ticker: str) -> EquityOrderIntent | None:
    session = _session()
    try:
        return session.scalar(
            select(EquityOrderIntent).where(
                EquityOrderIntent.case_id == case_id,
                EquityOrderIntent.ticker == ticker,
                EquityOrderIntent.status == "awaiting_approval",
            )
        )
    finally:
        session.close()


def list_for_case(case_id: str, *, status: str | None = None, limit: int = 20) -> list[EquityOrderIntent]:
    session = _session()
    try:
        stmt = select(EquityOrderIntent).where(EquityOrderIntent.case_id == case_id)
        if status:
            stmt = stmt.where(EquityOrderIntent.status == status)
        stmt = stmt.order_by(EquityOrderIntent.submitted_at.desc().nullslast()).limit(limit)
        return list(session.scalars(stmt))
    finally:
        session.close()


def sweep_abandoned(case_id: str, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - intent_ttl()
    session = _session()
    try:
        result = session.execute(
            update(EquityOrderIntent)
            .where(
                EquityOrderIntent.case_id == case_id,
                EquityOrderIntent.status == "awaiting_approval",
                EquityOrderIntent.submitted_at.is_not(None),
                EquityOrderIntent.submitted_at < cutoff,
            )
            .values(status="abandoned")
        )
        session.commit()
        return result.rowcount or 0
    finally:
        session.close()


def _fill_existing(
    row: EquityOrderIntent,
    *,
    status: str,
    notional_price: Decimal | None,
    notional_czk: Decimal | None,
    quote_source: str | None,
    fx_czk_per_unit: Decimal | None,
    fx_date: Any,
    fx_source: str | None,
    error_code: str | None,
    rationale: str | None,
    now: datetime,
) -> None:
    row.status = status
    row.error_code = error_code
    row.notional_price = notional_price
    row.notional_czk = notional_czk
    row.quote_source = quote_source
    row.fx_czk_per_unit = fx_czk_per_unit
    row.fx_date = fx_date
    row.fx_source = fx_source
    if rationale:
        row.rationale = rationale
    if row.submitted_at is None:
        row.submitted_at = now


def _new_row(
    *,
    case_id: str,
    inputs: OrderInput,
    status: str,
    digest: str,
    correlation_id: str | None,
    tool_name: str,
    notional_price: Decimal | None,
    notional_czk: Decimal | None,
    quote_source: str | None,
    fx_czk_per_unit: Decimal | None,
    fx_date: Any,
    fx_source: str | None,
    error_code: str | None,
    rationale: str | None,
    now: datetime,
) -> EquityOrderIntent:
    return EquityOrderIntent(
        id=uuid4(),
        case_id=case_id,
        request_id=uuid4(),
        status=status,
        ticker=inputs.ticker,
        side=inputs.side.value,
        order_type=inputs.order_type.value,
        quantity=inputs.quantity,
        limit_price=inputs.limit_price,
        stop_price=inputs.stop_price,
        time_validity=inputs.time_validity.value if inputs.time_validity else None,
        extended_hours=inputs.extended_hours,
        notional_price=notional_price,
        quote_source=quote_source,
        notional_czk=notional_czk,
        fx_czk_per_unit=fx_czk_per_unit,
        fx_date=fx_date,
        fx_source=fx_source,
        payload_hash=digest,
        correlation_id=correlation_id,
        tool_name=tool_name,
        rationale=rationale,
        submitted_at=now,
        error_code=error_code,
    )


def _release_other_pending(session, *, case_id: str, ticker: str, keep_id: Any) -> None:
    rows = session.scalars(
        select(EquityOrderIntent).where(
            EquityOrderIntent.case_id == case_id,
            EquityOrderIntent.ticker == ticker,
            EquityOrderIntent.status == "awaiting_approval",
        )
    )
    for pending in rows:
        if keep_id is not None and pending.id == keep_id:
            continue
        pending.status = "abandoned"
        pending.correlation_id = None
    session.flush()


def _apply_write(
    session,
    *,
    case_id: str,
    inputs: OrderInput,
    status: str,
    digest: str,
    correlation_id: str | None,
    tool_name: str,
    notional_price: Decimal | None,
    notional_czk: Decimal | None,
    quote_source: str | None,
    fx_czk_per_unit: Decimal | None,
    fx_date: Any,
    fx_source: str | None,
    error_code: str | None,
    rationale: str | None,
    now: datetime,
) -> IntentWrite:
    row = None
    if correlation_id:
        row = session.scalar(_active_stmt(case_id, correlation_id, tool_name))
    if status == "awaiting_approval":
        _release_other_pending(session, case_id=case_id, ticker=inputs.ticker, keep_id=row.id if row else None)
    if row is None:
        row = _new_row(
            case_id=case_id,
            inputs=inputs,
            status=status,
            digest=digest,
            correlation_id=correlation_id,
            tool_name=tool_name,
            notional_price=notional_price,
            notional_czk=notional_czk,
            quote_source=quote_source,
            fx_czk_per_unit=fx_czk_per_unit,
            fx_date=fx_date,
            fx_source=fx_source,
            error_code=error_code,
            rationale=rationale,
            now=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return IntentWrite(row)
    if row.payload_hash == digest:
        _fill_existing(
            row,
            status=status,
            notional_price=notional_price,
            notional_czk=notional_czk,
            quote_source=quote_source,
            fx_czk_per_unit=fx_czk_per_unit,
            fx_date=fx_date,
            fx_source=fx_source,
            error_code=error_code,
            rationale=rationale,
            now=now,
        )
        session.commit()
        session.refresh(row)
        return IntentWrite(row)
    if row.status in TERMINAL_STATUSES:
        return IntentWrite(row, conflict=True)
    row.status = "abandoned"
    row.correlation_id = None
    session.flush()
    created = _new_row(
        case_id=case_id,
        inputs=inputs,
        status=status,
        digest=digest,
        correlation_id=correlation_id,
        tool_name=tool_name,
        notional_price=notional_price,
        notional_czk=notional_czk,
        quote_source=quote_source,
        fx_czk_per_unit=fx_czk_per_unit,
        fx_date=fx_date,
        fx_source=fx_source,
        error_code=error_code,
        rationale=rationale,
        now=now,
    )
    session.add(created)
    session.commit()
    session.refresh(created)
    return IntentWrite(created)


def upsert_intent(
    *,
    case_id: str,
    inputs: OrderInput,
    status: str,
    tool_name: str,
    correlation_id: str | None,
    notional_price: Decimal | None,
    notional_czk: Decimal | None,
    quote_source: str | None,
    fx_czk_per_unit: Decimal | None,
    fx_date: Any,
    fx_source: str | None,
    error_code: str | None = None,
    rationale: str | None = None,
) -> IntentWrite:
    session = _session()
    digest = payload_hash(inputs)
    correlation_id = clean_correlation(correlation_id)
    now = datetime.now(timezone.utc)
    kwargs = dict(
        case_id=case_id,
        inputs=inputs,
        status=status,
        digest=digest,
        correlation_id=correlation_id,
        tool_name=tool_name,
        notional_price=notional_price,
        notional_czk=notional_czk,
        quote_source=quote_source,
        fx_czk_per_unit=fx_czk_per_unit,
        fx_date=fx_date,
        fx_source=fx_source,
        error_code=error_code,
        rationale=rationale,
        now=now,
    )
    try:
        try:
            return _apply_write(session, **kwargs)
        except IntegrityError:
            session.rollback()
            if not correlation_id:
                raise
            winner = session.scalar(_active_stmt(case_id, correlation_id, tool_name))
            if winner is None:
                raise
            if winner.payload_hash == digest:
                _fill_existing(
                    winner,
                    status=status,
                    notional_price=notional_price,
                    notional_czk=notional_czk,
                    quote_source=quote_source,
                    fx_czk_per_unit=fx_czk_per_unit,
                    fx_date=fx_date,
                    fx_source=fx_source,
                    error_code=error_code,
                    rationale=rationale,
                    now=now,
                )
                session.commit()
                session.refresh(winner)
                return IntentWrite(winner)
            return IntentWrite(winner, conflict=True)
    finally:
        session.close()


def mark_status(
    intent_id: UUID,
    status: str,
    *,
    error_code: str | None = None,
    t212_order_id: str | None = None,
    broker_message: str | None = None,
    confirmed: bool = False,
) -> EquityOrderIntent:
    session = _session()
    try:
        row = session.get(EquityOrderIntent, intent_id)
        if row is None:
            raise KeyError(str(intent_id))
        row.status = status
        if error_code is not None:
            row.error_code = error_code
        if t212_order_id is not None:
            row.t212_order_id = t212_order_id
        if broker_message is not None:
            row.broker_message = broker_message
        if confirmed:
            row.confirmed_at = datetime.now(timezone.utc)
        if status == "executed":
            row.executed_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(row)
        return row
    finally:
        session.close()


def get_intent(intent_id: UUID) -> EquityOrderIntent | None:
    session = _session()
    try:
        return session.get(EquityOrderIntent, intent_id)
    finally:
        session.close()
