"""add name to users

Revision ID: 001
Revises: 000
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


def downgrade() -> None:
    op.drop_column("users", "name")
