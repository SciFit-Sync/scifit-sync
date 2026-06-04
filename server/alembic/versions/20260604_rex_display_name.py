"""routine_exercises.display_name 컬럼 추가 (PR-3 기구-중심 루틴 생성: 선택 동작 라벨 스냅샷)

Revision ID: 20260604_rex_display_name
Revises: 20260604_machine_templates
Create Date: 2026-06-04

PR-3가 routine_exercises에 display_name(LLM이 선택한 equipment_label 스냅샷)을 저장한다.
모델(app/models/routine.py RoutineExercise.display_name)과 DB 정합을 위한 additive 컬럼.
"""

from alembic import op

revision = "20260604_rex_display_name"
down_revision = "20260604_machine_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE routine_exercises ADD COLUMN IF NOT EXISTS display_name varchar(200) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE routine_exercises DROP COLUMN IF EXISTS display_name")
