"""Assisted Dip/Chin 복합 정의 + 라벨 정합성 (arms followup-3)

Revision ID: 20260605_dipchin_compound
Revises: 20260605_latpulldown_sec
Create Date: 2026-06-05

배경 (arm-equipment-followups 핸드오프 followup-3, 사용자 결정 = '복합'):
  equipment 2ca108c5 실제명 = 'Assisted Dip/Chin'(보조 딥/친업 머신, category=arms)인데
  movement_label_en = 'Cable Triceps Pushdown' 으로 박혀 있어, 라벨 JOIN 백필(followup-1)이
  삼두근 primary 하나만 부여한다. 그러나 이 기구는 두 복합운동을 보조:
    - Dip  = 가슴(대흉근) + 삼두 (+ 전면삼각근 보조)
    - Chin = 등(광배근) + 이두 (+ 전완근 보조)

해결 (사용자 결정 = 복합 정의):
  ① movement_label_en 을 실제 정체 'Assisted Dip/Chin' 으로 교정(데이터 정합성).
  ② equipment_muscles 를 복합 세트로 재정의 (DELETE→INSERT, slug JOIN). 직접 부여이므로
     라벨-템플릿 JOIN 에 의존하지 않는다(전용 template 운동 불필요).

★ equipment_id 는 결정론 uuid5(환경 동일, #284 패턴) 리터럴. muscle_group_id 는 slug JOIN(하드코딩 금지).
멱등: DELETE→INSERT(ON CONFLICT DO UPDATE) 반복 시 동일 최종 상태.
안전: equipment_muscles 순수 참조 데이터 → 사용자 루틴/기록 무관. downgrade no-op.
주의: 삼두근·이두근 둘 다 primary → 머신 팔 필터(삼두/이두 루틴 양쪽)에 정상 포착. 가슴/등 primary 로
  해당 부위 루틴에도 후보가 됨(복합 머신의 의도된 다용도성).
"""

from alembic import op
from sqlalchemy import text

revision = "20260605_dipchin_compound"
down_revision = "20260605_latpulldown_sec"
branch_labels = None
depends_on = None

_EQ_ID = "2ca108c5-6153-5b7b-9b22-530ef902178c"  # Assisted Dip/Chin (arms)

# 복합 정의: Dip(가슴+삼두+전면삼각근) + Chin(광배+이두+전완근)
_MUSCLES = [
    ("pectoralis_major", "primary", 80),
    ("triceps_brachii", "primary", 80),
    ("latissimus_dorsi", "primary", 80),
    ("biceps_brachii", "primary", 75),
    ("anterior_deltoid", "secondary", 40),
    ("forearms", "secondary", 35),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ① 라벨 교정: 'Cable Triceps Pushdown' → 'Assisted Dip/Chin' (실제 기구 정체).
    op.execute(f"UPDATE equipments SET movement_label_en = 'Assisted Dip/Chin' WHERE id = '{_EQ_ID}'")

    # ② equipment_muscles 복합 재정의 (DELETE → INSERT, slug JOIN). followup-1 의 삼두-only 를 교체.
    op.execute(f"DELETE FROM equipment_muscles WHERE equipment_id = '{_EQ_ID}'")
    for slug, inv, pct in _MUSCLES:
        conn.execute(
            text(
                """
                INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement, activation_pct)
                SELECT CAST(:eq AS uuid), m.id, CAST(:inv AS varchar), CAST(:pct AS integer)
                FROM muscle_groups m
                WHERE m.name = CAST(:slug AS varchar)
                ON CONFLICT (equipment_id, muscle_group_id)
                DO UPDATE SET involvement = EXCLUDED.involvement, activation_pct = EXCLUDED.activation_pct
                """
            ),
            {"eq": _EQ_ID, "inv": inv, "pct": pct, "slug": slug},
        )


def downgrade() -> None:
    # no-op: 이전(라벨 불일치 + 삼두-only) 상태 복원 무의미.
    pass
