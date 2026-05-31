"""user_profiles: career_years 컬럼 추가

Revision ID: 009
Revises: 008
Create Date: 2026-05-28
"""

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "20260528_fix_lexco_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("career_years", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "career_years")
