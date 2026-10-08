"""Host-neutral empty schema (no domain tables).

Revision ID: 0001_empty
Revises:
"""

from typing import Sequence, Union

revision: str = "0001_empty"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
