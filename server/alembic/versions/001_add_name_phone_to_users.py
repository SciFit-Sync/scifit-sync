"""add name and phone to users

Revision ID: 001
Revises:
Create Date: 2026-04-10
"""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = "000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "phone")
    op.drop_column("users", "name")
