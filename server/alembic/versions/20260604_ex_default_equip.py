"""exercises.default_equipment_id 추가 + 백필 (기구-중심 PR-4.5: exercise_equipment_map 읽기/쓰기 경로 제거 선행)

Revision ID: 20260604_ex_default_equip
Revises: 20260604_rex_equip_notnull
Create Date: 2026-06-04

PR-5에서 exercise_equipment_map(eem)을 DROP하려면 먼저 런타임이 eem을 읽지 않아야 한다.
eem이 보유한 정보 중 런타임에 계속 필요한 것은 "프리웨이트 운동 → 구현 기구(제네릭 바벨/덤벨)"
1:1 매핑뿐이다(머신은 movement_label_en==name_en 경로로 이미 해석됨, PR-1~3).

본 마이그레이션은 그 1:1 매핑을 exercises.default_equipment_id(nullable FK)로 이전한다:
- 프리웨이트 운동은 eem에서 정확히 1개 기구(is_freeweight=true)에 대응 → 무손실 이전.
- 머신 movement_template은 default_equipment_id를 두지 않는다(NULL 유지).

eem 테이블/모델 자체는 본 PR에서 유지하며, DROP은 PR-5(승인 게이트)에서 수행한다.
downgrade는 컬럼만 제거(비파괴, eem 원본 보존).
"""

from alembic import op

revision = "20260604_ex_default_equip"
down_revision = "20260604_rex_equip_notnull"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 컬럼 추가 (nullable FK, 기구 삭제 시 SET NULL)
    op.execute(
        "ALTER TABLE exercises ADD COLUMN IF NOT EXISTS default_equipment_id uuid "
        "REFERENCES equipments (id) ON DELETE SET NULL"
    )

    # 2) eem의 프리웨이트 행을 default_equipment_id로 결정론적 백필
    #    운동당 freeweight 기구는 사실상 1개지만, 만일을 대비해 DISTINCT ON으로 1개만 선택(결정론).
    op.execute(
        """
        UPDATE exercises ex
        SET default_equipment_id = sub.equipment_id
        FROM (
            SELECT DISTINCT ON (eem.exercise_id)
                   eem.exercise_id,
                   e.id AS equipment_id
            FROM exercise_equipment_map eem
            JOIN equipments e ON e.id = eem.equipment_id
            WHERE e.is_freeweight = true
            ORDER BY eem.exercise_id, e.equipment_type, e.id
        ) sub
        WHERE ex.id = sub.exercise_id
        """
    )


def downgrade() -> None:
    # 컬럼만 제거(비파괴). eem 원본 데이터는 그대로 유지된다.
    op.execute("ALTER TABLE exercises DROP COLUMN IF EXISTS default_equipment_id")
