"""exercises 테이블에 gif_url 컬럼 추가

WorkoutX API GIF URL 저장용.

Revision ID: 20260525_add_gif_url_exercises
Revises: 20260524_seed_ai_gym_equipments
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260525_add_gif_url_exercises"
down_revision = "20260524_seed_ai_gym_equipments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("exercises", sa.Column("gif_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("exercises", "gif_url")
