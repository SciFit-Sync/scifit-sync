"""equipment_muscles 결손 백필 — movement_label JOIN (결손 기구 한정)

Revision ID: 20260605_eqmuscle_deficit
Revises: 20260605_seed_activation
Create Date: 2026-06-05

배경 (arm-equipment-followups 핸드오프 followup-1, 진짜 prod hnwegx 실측):
  category=arms 19기구 중 18개가 equipment_muscles 행 0건(결손) → 머신 팔 필터
  (EquipmentMuscle.involvement=='primary', routines.py:_build_rag_profile)에서 누락.
  #284(arm garbage 교정)는 *오염된* 3기구만 외과적 교정했고, 대다수 결손 기구는 미해결.
  결손 기구들은 movement_label_en(Machine Biceps Curl / Machine Triceps Extension /
  Cable Triceps Pushdown / Preacher Curl Machine 등)을 갖고, 동명 template exercise 는
  선행 seed_activation 마이그가 exercise_muscles(이두근/삼두근 primary 등)를 시드해 둠.

해결 (eqmuscle_direct 의 movement_label_en→name_en JOIN 재사용):
  결손 기구(equipment_muscles 0행)에 한해 JOIN replay 로 백필.
  ★ NOT EXISTS(이미 매핑 보유) 가드 필수 — 전체 재실행은 #284 가 외과교정해 정리한 기구
    (예: Cable=latissimus_dorsi only)에 재오염을 일으킬 수 있다. 결손만 채워 기존 무접촉.

★ muscle_group_id 하드코딩 금지 — JOIN 으로 해석(prod muscle id 는 환경마다 다름).
멱등: 결손 기구가 없으면 0행. ON CONFLICT DO NOTHING. clean DB 는 eqmuscle_direct 가
  이미 채웠고 결손이 거의 없어 사실상 no-op.
안전: equipment_muscles 는 순수 매핑테이블 → 사용자 루틴/기록 무관.
downgrade no-op: 결손 백필 역행 무의미(어떤 행이 본 마이그 산출인지 PK 충돌로 구분 불가).
"""

from alembic import op

revision = "20260605_eqmuscle_deficit"
down_revision = "20260605_seed_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # eqmuscle_direct JOIN + 결손 기구 한정(NOT EXISTS). DISTINCT ON 으로 (eq, muscle)당 1행
    # 결정론 선택(primary 우선, activation DESC). ON CONFLICT 는 동시성 안전망.
    op.execute(
        """
        INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement, activation_pct)
        SELECT DISTINCT ON (e.id, xm.muscle_group_id)
            e.id, xm.muscle_group_id, xm.involvement, xm.activation_pct
        FROM equipments e
        JOIN exercises ex ON lower(ex.name_en) = lower(e.movement_label_en)
        JOIN exercise_muscles xm ON xm.exercise_id = ex.id
        WHERE e.movement_label_en IS NOT NULL
          AND e.equipment_type NOT IN ('barbell', 'dumbbell', 'bodyweight')
          AND NOT EXISTS (SELECT 1 FROM equipment_muscles em WHERE em.equipment_id = e.id)
        ORDER BY
            e.id,
            xm.muscle_group_id,
            (xm.involvement = 'primary') DESC,
            xm.activation_pct DESC NULLS LAST
        ON CONFLICT (equipment_id, muscle_group_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # no-op: 결손 백필분과 기존 행을 PK 로 구분 불가 → 안전한 단독 삭제 불가.
    pass
