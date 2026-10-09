"""Stored replies for outbound reads.

Revision ID: 0004_stored_api_replies
Revises: 0003_intent_correlation
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_stored_api_replies"
down_revision: Union[str, Sequence[str], None] = "0003_intent_correlation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stored_api_replies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("route", sa.String(length=256), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "route", "subject", name="uq_stored_api_replies_call"),
    )


def downgrade() -> None:
    op.drop_table("stored_api_replies")
