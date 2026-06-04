"""기구-중심 재설계 PR-1: equipments/equipment_muscles 컬럼 추가 + 머신 근육 백필

Revision ID: 20260604_equipment_centric_pr1
Revises: 20260604_exercise_equipment_map
Create Date: 2026-06-04

변경 사항:
  1. equipments.movement_label_ko / movement_label_en 컬럼 추가 (varchar 150, NULL)
  2. equipments.is_freeweight GENERATED ALWAYS AS STORED 컬럼 추가
     (equipment_type IN ('barbell','dumbbell','bodyweight'))
  3. equipment_muscles.activation_pct 컬럼 추가 (integer, NULL)
  4. equipment_muscles 백필: 머신(is_freeweight=false) 기구에 한해
     exercise_equipment_map + exercise_muscles 조인으로 primary 근육 도출.
     DISTINCT ON (equipment_id, muscle_group_id) + ORDER BY primary 우선/activation_pct DESC NULLS LAST
     결정론적 1행 선택. ON CONFLICT DO NOTHING.

롤백:
  - 컬럼 DROP (movement_label_ko, movement_label_en, is_freeweight, activation_pct)
  - 이 revision이 백필한 equipment_muscles 행 삭제
    (equipment_muscles는 현재 빈 테이블이므로 이 revision이 삽입한 전체가 대상)
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_equipment_centric_pr1"
down_revision = "20260604_exercise_equipment_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. equipments 컬럼 추가 ────────────────────────────────────────────────
    conn.execute(
        sa.text(
            """
            ALTER TABLE equipments
              ADD COLUMN IF NOT EXISTS movement_label_ko varchar(150) NULL,
              ADD COLUMN IF NOT EXISTS movement_label_en varchar(150) NULL
            """
        )
    )

    # GENERATED ALWAYS AS STORED: PostgreSQL 12+ 지원
    # IF NOT EXISTS 미지원 → 이미 존재하면 오류 방지를 위해 조건 체크 후 추가
    col_exists = conn.execute(
        sa.text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'equipments' AND column_name = 'is_freeweight'
            """
        )
    ).fetchone()

    if not col_exists:
        conn.execute(
            sa.text(
                """
                ALTER TABLE equipments
                  ADD COLUMN is_freeweight boolean
                  GENERATED ALWAYS AS (
                    equipment_type IN ('barbell', 'dumbbell', 'bodyweight')
                  ) STORED
                """
            )
        )

    # ── 2. equipment_muscles.activation_pct 컬럼 추가 ─────────────────────────
    conn.execute(
        sa.text(
            """
            ALTER TABLE equipment_muscles
              ADD COLUMN IF NOT EXISTS activation_pct integer NULL
            """
        )
    )

    # ── 3. 머신 기구 근육 백필 ─────────────────────────────────────────────────
    # exercise_equipment_map + exercise_muscles 조인으로
    # 각 머신 기구에 연결된 운동들의 primary 근육을 도출.
    # DISTINCT ON (equipment_id, muscle_group_id)로 중복 제거,
    # ORDER BY: primary 먼저(involvement='primary' → 사전순 뒤), activation_pct DESC NULLS LAST.
    # ON CONFLICT DO NOTHING으로 멱등성 보장.
    conn.execute(
        sa.text(
            """
            INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement, activation_pct)
            SELECT DISTINCT ON (eem.equipment_id, xm.muscle_group_id)
                eem.equipment_id,
                xm.muscle_group_id,
                xm.involvement,
                xm.activation_pct
            FROM exercise_equipment_map eem
            JOIN equipments e ON e.id = eem.equipment_id
            JOIN exercise_muscles xm ON xm.exercise_id = eem.exercise_id
            WHERE e.equipment_type NOT IN ('barbell', 'dumbbell', 'bodyweight')
            ORDER BY
                eem.equipment_id,
                xm.muscle_group_id,
                (xm.involvement = 'primary') DESC,
                xm.activation_pct DESC NULLS LAST
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # ── 3. 백필 행 제거 (머신 기구 관련 행 전체 삭제) ─────────────────────────
    # 이 revision이 삽입한 머신 기구의 equipment_muscles 행만 제거.
    # exercise_equipment_map을 소스로 삼아 머신 기구 식별.
    conn.execute(
        sa.text(
            """
            DELETE FROM equipment_muscles
            WHERE equipment_id IN (
                SELECT DISTINCT eem.equipment_id
                FROM exercise_equipment_map eem
                JOIN equipments e ON e.id = eem.equipment_id
                WHERE e.equipment_type NOT IN ('barbell', 'dumbbell', 'bodyweight')
            )
            """
        )
    )

    # ── 2. equipment_muscles.activation_pct 컬럼 DROP ─────────────────────────
    conn.execute(
        sa.text(
            """
            ALTER TABLE equipment_muscles
              DROP COLUMN IF EXISTS activation_pct
            """
        )
    )

    # ── 1. equipments 컬럼 DROP ────────────────────────────────────────────────
    conn.execute(
        sa.text(
            """
            ALTER TABLE equipments
              DROP COLUMN IF EXISTS is_freeweight,
              DROP COLUMN IF EXISTS movement_label_en,
              DROP COLUMN IF EXISTS movement_label_ko
            """
        )
    )
