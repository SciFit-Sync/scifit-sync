"""equipment_muscles movement_label 기반 직접 시드 (eem 비의존 보완)

Revision ID: 20260604_eqmuscle_direct
Revises: 20260604_ex_default_equip
Create Date: 2026-06-04

배경:
  PR-1(equipment_centric_pr1)은 equipment_muscles를 exercise_equipment_map(eem) ⋈
  exercise_muscles 경로로 백필한다. 이 방식은 eem에 매핑된 머신만 근육을 얻으므로,
  eem 커버리지가 불완전하면(seed_exercise_equipment_map에 안 엮인 찬스짐 머신 등)
  근육 필터(_build_rag_profile 머신 후보)에서 누락되어 "머신이 안 나오는" 증상이 생긴다.

변경:
  movement_label_en 기반으로 equipment_muscles를 직접 시드한다. PR-2(seed_machine_
  movement_templates)가 머신 기구마다 movement_label_en을 백필하고 동명의 movement_
  template exercise(name_en == movement_label_en)에 exercise_muscles를 시드하므로,
  equipments ⋈ exercises[name_en = movement_label_en] ⋈ exercise_muscles 로
  eem을 거치지 않고 기구 근육을 도출한다. PR-1 백필과 ON CONFLICT DO NOTHING으로 공존.

비파괴:
  upgrade는 INSERT만(기존 행 미변경). downgrade는 no-op — 이 마이그레이션이 추가한
  행은 PR-1 백필분과 (equipment_id, muscle_group_id) PK로 겹칠 수 있어 안전한 단독
  삭제가 불가능하다. equipment_muscles 정리는 PR-1(equipment_centric_pr1) downgrade가
  담당한다.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_eqmuscle_direct"
down_revision = "20260604_ex_default_equip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # movement_label_en == exercises.name_en JOIN으로 머신 기구의 근육을 직접 도출.
    # DISTINCT ON + ORDER BY로 (equipment_id, muscle_group_id)당 1행 결정론 선택
    # (primary 우선, activation_pct DESC NULLS LAST). ON CONFLICT로 PR-1 백필과 멱등 공존.
    conn.execute(
        sa.text(
            """
            INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement, activation_pct)
            SELECT DISTINCT ON (e.id, xm.muscle_group_id)
                e.id,
                xm.muscle_group_id,
                xm.involvement,
                xm.activation_pct
            FROM equipments e
            JOIN exercises ex ON lower(ex.name_en) = lower(e.movement_label_en)
            JOIN exercise_muscles xm ON xm.exercise_id = ex.id
            WHERE e.movement_label_en IS NOT NULL
              AND e.equipment_type NOT IN ('barbell', 'dumbbell', 'bodyweight')
            ORDER BY
                e.id,
                xm.muscle_group_id,
                (xm.involvement = 'primary') DESC,
                xm.activation_pct DESC NULLS LAST
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # no-op (위 docstring 참조: PR-1 백필분과 PK 충돌 가능 → 단독 삭제 불가).
    pass
