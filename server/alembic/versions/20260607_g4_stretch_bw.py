"""G4 — assisted 스트레치/맨몸 운동 load_mode machine→bodyweight 정정.

Revision ID: 20260607_g4_stretch_bw
Revises: 20260607_seed_junction
Create Date: 2026-06-07

배경(G4):
  reseed_workoutx 의 _WX_LOAD_MODE 가 WorkoutX equipment='assisted'/'assisted (towel)' 를
  일괄 load_mode='machine' 으로 매핑했다. 그러나 해당 15운동은 전부 **파트너/맨몸/스트레치**
  (Assisted ... Stretch, Hanging Knee Raise, Lying Leg Raise, Sit-up, Prone Hamstring,
   Towel Triceps Extension)로 머신 부하(stack/pulley)가 없다. 머신 보조기구(Assisted Dip/Chin)는
  equipment 가 'assisted' 가 아니라 이 집합에 없다.

문제:
  load_mode='machine' 이면 load_calc.py 의 cable|machine 분기(stack/pulley 계산)를 타 무의미한
  실효부하가 나온다. 부하 없는 스트레치/맨몸은 load_mode='bodyweight'(체중 기반, 프리웨이트
  baseline)가 정합한다.

조치:
  1) 15운동 load_mode machine→bodyweight (멱등: load_mode='machine' 인 행만).
  2) bodyweight=프리웨이트 baseline(항상 가용)이라 머신 junction 이 잉여 → 해당 운동의
     exercise_equipment 행 제거(seed_junction 이 Sit-up/Towel 2건을 넣었음).

[논문 절대 불가침] papers / paper_chunks 에 대한 DELETE/DROP/ALTER 0건.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260607_g4_stretch_bw"
down_revision = "20260607_seed_junction"
branch_labels = None
depends_on = None

# equipment='assisted'/'assisted (towel)' 였던 15운동 (전부 파트너/맨몸/스트레치).
_BODYWEIGHT_NAMES: list[str] = [
    "Assisted Hanging Knee Raise With Throw Down",
    "Assisted Hanging Knee Raise",
    "Assisted Lying Leg Raise With Lateral Throw Down",
    "Assisted Lying Leg Raise With Throw Down",
    "Assisted Prone Hamstring",
    "Assisted Standing Triceps Extension (with Towel)",
    "Behind Head Chest Stretch",
    "Assisted Lying Calves Stretch",
    "Assisted Lying Glutes Stretch",
    "Assisted Lying Gluteus And Piriformis Stretch",
    "Assisted Side Lying Adductor Stretch",
    "Assisted Prone Lying Quads Stretch",
    "Assisted Prone Rectus Femoris Stretch",
    "Assisted Seated Pectoralis Major Stretch With Stability Ball",
    "Assisted Sit-up",
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1) load_mode machine→bodyweight (machine 인 행만 — 멱등).
    res = conn.execute(
        sa.text(
            """
            UPDATE exercises
            SET load_mode = 'bodyweight', updated_at = now()
            WHERE name_en = ANY(:names) AND load_mode = 'machine'
            """
        ),
        {"names": _BODYWEIGHT_NAMES},
    )

    # 2) bodyweight 전환분의 잉여 junction 제거(프리웨이트 baseline은 머신 가용성 불요).
    conn.execute(
        sa.text(
            """
            DELETE FROM exercise_equipment
            WHERE exercise_id IN (SELECT id FROM exercises WHERE name_en = ANY(:names))
            """
        ),
        {"names": _BODYWEIGHT_NAMES},
    )

    import logging

    logging.getLogger("alembic").info(
        "G4: assisted 스트레치/맨몸 %d행 load_mode→bodyweight + junction 제거.", res.rowcount or 0
    )


def downgrade() -> None:
    """역: bodyweight→machine. junction 복원은 seed_junction 재실행 필요(forward 권장)."""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE exercises
            SET load_mode = 'machine', updated_at = now()
            WHERE name_en = ANY(:names) AND load_mode = 'bodyweight'
            """
        ),
        {"names": _BODYWEIGHT_NAMES},
    )
