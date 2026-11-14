"""Arabic names for contacts and companies.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14 13:10:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("name_ar", sa.String(255), nullable=True))
    op.add_column("contacts", sa.Column("name_ar", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("contacts", "name_ar")
    op.drop_column("companies", "name_ar")
