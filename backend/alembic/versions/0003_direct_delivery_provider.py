"""Add the built-in direct-delivery provider.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14 10:40:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE provider ADD VALUE IF NOT EXISTS 'direct'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; direct accounts must be removed manually first.
    pass
