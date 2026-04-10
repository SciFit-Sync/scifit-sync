"""add name and phone to users

Revision ID: 001
Revises:
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    # users 테이블이 없으면 스킵 (create_tables.py로 생성 시 이미 컬럼 포함)
    if not insp.has_table("users"):
        return
    existing_columns = {col["name"] for col in insp.get_columns("users")}
    if "name" not in existing_columns:
        op.add_column("users", sa.Column("name", sa.String(100), nullable=True))
    if "phone" not in existing_columns:
        op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if not insp.has_table("users"):
        return
    existing_columns = {col["name"] for col in insp.get_columns("users")}
    if "phone" in existing_columns:
        op.drop_column("users", "phone")
    if "name" in existing_columns:
        op.drop_column("users", "name")
