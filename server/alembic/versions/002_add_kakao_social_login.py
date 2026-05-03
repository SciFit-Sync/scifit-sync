"""add kakao social login

Revision ID: 002
Revises: 001
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("kakao_id", sa.String(50), nullable=True))
    op.create_unique_constraint("uq_users_kakao_id", "users", ["kakao_id"])
    op.create_index("ix_users_kakao_id", "users", ["kakao_id"])
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    op.drop_index("ix_users_kakao_id", table_name="users")
    op.drop_constraint("uq_users_kakao_id", "users", type_="unique")
    op.drop_column("users", "kakao_id")
