"""랫풀다운 보조근 상류 보강 (arms followup-2)

Revision ID: 20260605_latpulldown_sec
Revises: 20260605_eqmuscle_deficit
Create Date: 2026-06-05

배경 (arm-equipment-followups 핸드오프 followup-2):
  'Machine Lat Pulldown' template exercise 는 seed_activation 에서 latissimus_dorsi(primary)
  하나만 갖는다. 운동학적으로 랫풀다운 보조근 = 이두근/능형근/승모근(하부)/후면삼각근.
  → 같은 label 기구들이 광배근 primary 만 표시(보조근 누락). 머신 팔 필터(primary)엔 무관,
  근육 활성도 *표시 정확도*만 개선.

해결 (상류 보강 = 권장):
  ① template exercise 'Machine Lat Pulldown' 에 보조근 4종(secondary) 추가
  ② 동일 label 기구에 eqmuscle_direct JOIN 으로 전파(ON CONFLICT DO NOTHING → primary 무접촉, 보조근만 추가)

★ muscle_group_id 하드코딩 금지 — slug JOIN. asyncpg: bare-select param 은 CAST.
멱등: ON CONFLICT DO NOTHING. exercise 미존재 환경은 SELECT 0행 → no-op.
안전: 순수 참조 데이터. downgrade no-op.
"""

from alembic import op
from sqlalchemy import text

revision = "20260605_latpulldown_sec"
down_revision = "20260605_eqmuscle_deficit"
branch_labels = None
depends_on = None

_LAT_EXERCISE = "Machine Lat Pulldown"
# 보조근 (slug, activation_pct) — 랫풀다운 운동학 기반 secondary
_SECONDARIES = [
    ("biceps_brachii", 50),
    ("rhomboids", 45),
    ("trapezius", 40),
    ("posterior_deltoid", 35),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ① template exercise 에 보조근 추가 (멱등). slug JOIN, bare-select 값은 CAST.
    for slug, pct in _SECONDARIES:
        conn.execute(
            text(
                """
                INSERT INTO exercise_muscles (exercise_id, muscle_group_id, involvement, activation_pct)
                SELECT e.id, m.id, 'secondary', CAST(:pct AS integer)
                FROM exercises e
                JOIN muscle_groups m ON m.name = CAST(:slug AS varchar)
                WHERE e.name_en = CAST(:nm AS varchar)
                ON CONFLICT (exercise_id, muscle_group_id) DO NOTHING
                """
            ),
            {"slug": slug, "pct": pct, "nm": _LAT_EXERCISE},
        )

    # ② 동일 label 기구에 전파 (eqmuscle_direct JOIN, 이 운동 한정).
    #    ON CONFLICT DO NOTHING → 기존 primary/보유근 무접촉, 신규 보조근만 추가.
    op.execute(
        f"""
        INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement, activation_pct)
        SELECT DISTINCT ON (e.id, xm.muscle_group_id)
            e.id, xm.muscle_group_id, xm.involvement, xm.activation_pct
        FROM equipments e
        JOIN exercises ex ON lower(ex.name_en) = lower(e.movement_label_en)
        JOIN exercise_muscles xm ON xm.exercise_id = ex.id
        WHERE lower(ex.name_en) = lower('{_LAT_EXERCISE}')
          AND e.equipment_type NOT IN ('barbell', 'dumbbell', 'bodyweight')
        ORDER BY
            e.id,
            xm.muscle_group_id,
            (xm.involvement = 'primary') DESC,
            xm.activation_pct DESC NULLS LAST
        ON CONFLICT (equipment_id, muscle_group_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # no-op: 보강분과 기존 행 구분 불가(PK 충돌). 정리는 상위 시드 정책 담당.
    pass
