"""add equipment_suggestions table

Revision ID: 006
Revises: 005
Create Date: 2026-05-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "gym_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
    )
    op.create_index("ix_equipment_suggestions_gym_id", "equipment_suggestions", ["gym_id"])
    op.create_index("ix_equipment_suggestions_user_id", "equipment_suggestions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_equipment_suggestions_user_id", table_name="equipment_suggestions")
    op.drop_index("ix_equipment_suggestions_gym_id", table_name="equipment_suggestions")
    op.drop_table("equipment_suggestions")
