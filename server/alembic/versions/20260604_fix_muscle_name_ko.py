"""fix: pectoralis_major.name_ko '가슴' → '대흉근' 교정

Revision ID: 20260604_fix_muscle_name_ko
Revises: 20260604_rex_equip_notnull
Create Date: 2026-06-04

배경:
  20260603_dedup_muscles 가 pectoralis_major 의 name_ko 를 구어체 "가슴"으로 덮어써
  근육 활성도 카드에 "대흉근" 대신 "가슴"이 표시되는 버그 발생.
  pectoralis_minor 는 "소흉근"이 그대로 유지돼 있으므로 본 마이그레이션은
  pectoralis_major 만 교정한다.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_fix_muscle_name_ko"
down_revision = "20260604_eqmuscle_direct"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE muscle_groups SET name_ko = '대흉근' WHERE name = 'pectoralis_major'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE muscle_groups SET name_ko = '가슴' WHERE name = 'pectoralis_major'"))
