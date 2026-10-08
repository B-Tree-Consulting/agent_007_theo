"""Host-minted order correlation.

Revision ID: 0003_intent_correlation
Revises: 0002_theo_intents
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_intent_correlation"
down_revision: Union[str, Sequence[str], None] = "0002_theo_intents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("equity_order_intents", sa.Column("correlation_id", sa.String(length=256), nullable=True))
    op.add_column("equity_order_intents", sa.Column("tool_name", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_equity_order_intents_correlation_tool",
        "equity_order_intents",
        ["case_id", "correlation_id", "tool_name"],
        unique=True,
        postgresql_where=sa.text("correlation_id IS NOT NULL AND status <> 'abandoned'"),
    )


def downgrade() -> None:
    op.drop_index("uq_equity_order_intents_correlation_tool", table_name="equity_order_intents")
    op.drop_column("equity_order_intents", "tool_name")
    op.drop_column("equity_order_intents", "correlation_id")
