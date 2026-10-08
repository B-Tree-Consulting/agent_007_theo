"""SQLAlchemy models for equity intents and CNB cache."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class EquityOrderIntent(Base):
    __tablename__ = "equity_order_intents"
    __table_args__ = (
        UniqueConstraint("case_id", "request_id", name="uq_equity_order_intents_case_request"),
        Index(
            "uq_equity_order_intents_pending_ticker",
            "case_id",
            "ticker",
            unique=True,
            postgresql_where=text("status = 'awaiting_approval'"),
        ),
        Index(
            "uq_equity_order_intents_correlation_tool",
            "case_id",
            "correlation_id",
            "tool_name",
            unique=True,
            postgresql_where=text("correlation_id IS NOT NULL AND status <> 'abandoned'"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[str] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[str] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    time_validity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extended_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notional_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    quote_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notional_czk: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    fx_czk_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    fx_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fx_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_token_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    approval_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    t212_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broker_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CnbFxFixing(Base):
    __tablename__ = "cnb_fx_fixings"

    currency_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    czk_per_unit: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    fixing_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="CNB")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
