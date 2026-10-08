"""Theo equity intents and CNB FX cache.

Revision ID: 0002_theo_intents
Revises: 0001_empty
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_theo_intents"
down_revision: Union[str, Sequence[str], None] = "0001_empty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "equity_order_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("ticker", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("limit_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("stop_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("time_validity", sa.String(length=32), nullable=True),
        sa.Column("extended_hours", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notional_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("quote_source", sa.String(length=64), nullable=True),
        sa.Column("notional_czk", sa.Numeric(28, 8), nullable=True),
        sa.Column("fx_czk_per_unit", sa.Numeric(28, 8), nullable=True),
        sa.Column("fx_date", sa.Date(), nullable=True),
        sa.Column("fx_source", sa.String(length=32), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_token_ref", sa.String(length=256), nullable=True),
        sa.Column("approval_record_id", sa.String(length=128), nullable=True),
        sa.Column("t212_order_id", sa.String(length=64), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("broker_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("case_id", "request_id", name="uq_equity_order_intents_case_request"),
    )
    op.create_index(
        "uq_equity_order_intents_pending_ticker",
        "equity_order_intents",
        ["case_id", "ticker"],
        unique=True,
        postgresql_where=sa.text("status = 'awaiting_approval'"),
    )
    op.create_table(
        "cnb_fx_fixings",
        sa.Column("currency_code", sa.String(length=8), primary_key=True, nullable=False),
        sa.Column("czk_per_unit", sa.Numeric(28, 8), nullable=False),
        sa.Column("fixing_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="CNB"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cnb_fx_fixings")
    op.drop_index("uq_equity_order_intents_pending_ticker", table_name="equity_order_intents")
    op.drop_table("equity_order_intents")
