"""찬스짐 33개 기구와 운동(exercises)을 exercise_equipment_map에 연결

Revision ID: 20260604_exercise_equipment_map
Revises: 20260603_dedup_muscles
Create Date: 2026-06-04

배경:
  exercise_equipment_map 테이블이 비어있어 gym_id가 주어져도 available_exercises = []
  → fallback으로 전체 DB 운동 목록이 LLM에 전달되는 버그.

전략:
  - 운동 ID를 하드코딩하지 않고 name_en JOIN으로 조회 (ON CONFLICT DO NOTHING 후 UUID 불일치 방지)
  - 기구 ID는 20260527_seed_chancegym_equipments 의 결정론적 UUID 직접 참조
  - Plank, Crunch 등 bodyweight 운동은 제외 (장비 불필요)

커버리지:
  가슴 5종, 등 5종, 어깨 4종, 팔 4종, 코어 1종, 하체 7종 = 총 26종 운동
  찬스짐 기구 사용: Barbell, Dumbbell, Smith machine 포함 33종 중 적용 가능한 29종
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_exercise_equipment_map"
down_revision = "20260603_dedup_muscles"
branch_labels = None
depends_on = None

# ── 운동↔기구 매핑 ─────────────────────────────────────────────────────────────
# (exercise.name_en, equipment.id)
# 기구 UUID 출처: 20260527_seed_chancegym_equipments.py
_EXERCISE_EQUIPMENT = [
    # ── 가슴 ──────────────────────────────────────────────────────────────────
    ("Bench Press", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Bench Press", "fe005947-b93d-5c51-bdb9-9dad2a8d11bb"),  # Smith machine
    ("Bench Press", "4989dc12-d0be-580d-a9b6-219ebd81add2"),  # Chest Press Newtech
    ("Incline Bench Press", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Incline Bench Press", "fe005947-b93d-5c51-bdb9-9dad2a8d11bb"),  # Smith machine
    ("Incline Bench Press", "8db23cf2-ff9a-580f-8615-55c1f5b7d2d8"),  # Plate Loaded Incline Press Lexco
    ("Incline Bench Press", "59c360a7-6bab-5bdd-af4f-f642a0b29089"),  # Incline Press Newtech
    ("Dumbbell Fly", "a0b9376d-c6b1-5ea9-bb64-91b11560deae"),  # Dumbbell
    ("Dips", "2ca108c5-6153-5b7b-9b22-530ef902178c"),  # Assisted Dip/Chin Newtech
    ("Cable Crossover", "bf3d0dde-84e3-510c-a43c-d0b017565431"),  # Cable Lexco
    ("Cable Crossover", "e94bec5c-a634-58e9-872f-8f63eee2b625"),  # Cable Newtech
    ("Cable Crossover", "9f5ad84b-ff44-5267-83e5-b1eaf7e3bf8d"),  # Pectoral Fly/Rear Deltoid Newtech
    ("Cable Crossover", "d1547e9f-ba27-5993-9b4e-6f5d5f7661e8"),  # Pec Fly/Rear Delt Lexco
    # ── 등 ────────────────────────────────────────────────────────────────────
    ("Conventional Deadlift", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Conventional Deadlift", "fe005947-b93d-5c51-bdb9-9dad2a8d11bb"),  # Smith machine
    ("Barbell Row", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Barbell Row", "fe005947-b93d-5c51-bdb9-9dad2a8d11bb"),  # Smith machine
    ("Barbell Row", "be8c8a43-281e-5331-8539-e5ecf1b2cba1"),  # M-Torture Front Row Newtech
    ("Pull Up", "2ca108c5-6153-5b7b-9b22-530ef902178c"),  # Assisted Dip/Chin (chin-up 모드)
    ("Seated Cable Row", "dc823fdb-8cc0-59db-8d4a-7fd03575723d"),  # Low Pulley Newtech
    ("Seated Cable Row", "14eea95a-3c5f-5e5d-a31e-37ac32953b2a"),  # Plate Loaded Seated Row Lexco
    ("Seated Cable Row", "c92e39a8-4faf-59d4-9bcb-fad9de96c2df"),  # Seated Row Lexco
    ("Lat Pulldown", "fa0d0b81-9759-5f4b-8567-ba9a23a0a4ea"),  # Lat Pulldown Newtech
    ("Lat Pulldown", "325e25e2-4b64-5d2b-8e8e-e6871f9657b3"),  # Lat Pulldown Lexco
    ("Lat Pulldown", "568857d6-f3e0-5905-9f60-18ce5180a4e1"),  # Plate Loaded Pulldown Lexco
    # ── 어깨 ──────────────────────────────────────────────────────────────────
    ("Overhead Press", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Overhead Press", "fe005947-b93d-5c51-bdb9-9dad2a8d11bb"),  # Smith machine
    ("Overhead Press", "48255be6-dd0b-564a-9c80-65969f2f7f81"),  # Plate Loaded Shoulder Press Lexco
    ("Dumbbell Shoulder Press", "a0b9376d-c6b1-5ea9-bb64-91b11560deae"),  # Dumbbell
    ("Dumbbell Shoulder Press", "a97c569a-fda7-5431-b694-14fac355921d"),  # Shoulder Press Newtech
    ("Side Lateral Raise", "a0b9376d-c6b1-5ea9-bb64-91b11560deae"),  # Dumbbell
    ("Side Lateral Raise", "bf3d0dde-84e3-510c-a43c-d0b017565431"),  # Cable Lexco
    ("Side Lateral Raise", "e94bec5c-a634-58e9-872f-8f63eee2b625"),  # Cable Newtech
    ("Face Pull", "bf3d0dde-84e3-510c-a43c-d0b017565431"),  # Cable Lexco
    ("Face Pull", "e94bec5c-a634-58e9-872f-8f63eee2b625"),  # Cable Newtech
    ("Face Pull", "9f5ad84b-ff44-5267-83e5-b1eaf7e3bf8d"),  # Pectoral Fly/Rear Deltoid Newtech
    ("Face Pull", "d1547e9f-ba27-5993-9b4e-6f5d5f7661e8"),  # Pec Fly/Rear Delt Lexco
    # ── 팔 ────────────────────────────────────────────────────────────────────
    ("Barbell Curl", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Barbell Curl", "45efe227-5806-5d60-90e3-30dd1850c16a"),  # Preacher Curl GYM80
    ("Dumbbell Hammer Curl", "a0b9376d-c6b1-5ea9-bb64-91b11560deae"),  # Dumbbell
    ("Tricep Pushdown", "bf3d0dde-84e3-510c-a43c-d0b017565431"),  # Cable Lexco
    ("Tricep Pushdown", "e94bec5c-a634-58e9-872f-8f63eee2b625"),  # Cable Newtech
    ("Skull Crusher", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Skull Crusher", "a0b9376d-c6b1-5ea9-bb64-91b11560deae"),  # Dumbbell
    # ── 코어 ──────────────────────────────────────────────────────────────────
    # Plank, Crunch: bodyweight → 장비 불필요, exercise_equipment_map 제외
    ("Cable Crunch", "bf3d0dde-84e3-510c-a43c-d0b017565431"),  # Cable Lexco
    ("Cable Crunch", "e94bec5c-a634-58e9-872f-8f63eee2b625"),  # Cable Newtech
    # ── 하체 ──────────────────────────────────────────────────────────────────
    ("Back Squat", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Back Squat", "fe005947-b93d-5c51-bdb9-9dad2a8d11bb"),  # Smith machine
    ("Back Squat", "8e672b7c-89b9-5596-aaa4-f20d888b3386"),  # Hack Squat GYM80
    ("Back Squat", "f19ec570-cfe3-5093-8bc2-764ce5e43d26"),  # Hack Slide Lexco
    ("Leg Press", "351ce983-fa20-5676-a05c-37e7cf9b4837"),  # Leg Press Newtech
    ("Leg Press", "f9fadf1e-6004-5297-b8d3-7b7a9c1a1bb1"),  # Seated Leg Press Newtech
    ("Leg Extension", "f13b498f-5922-5387-806b-be9639fee4c3"),  # Leg extension Lexco
    ("Leg Extension", "ca9ba9fb-5a5a-56c1-9937-73c500b62220"),  # Leg extension Newtech
    ("Leg Curl", "7d60b6f1-912d-5d6b-9585-2ac56d8f4c1a"),  # Seated leg curl Lexco
    ("Leg Curl", "d12dd92d-9357-59ab-a391-9883b0bc994c"),  # Leg curl Lexco
    ("Romanian Deadlift", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Romanian Deadlift", "a0b9376d-c6b1-5ea9-bb64-91b11560deae"),  # Dumbbell
    ("Hip Thrust", "b3266141-9f33-5929-a6ee-26e78ee3ac46"),  # Hip Thrust Machine Booty Builder
    ("Hip Thrust", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Calf Raise", "f970fcc9-53e4-5c3c-9faf-24baa5105448"),  # Barbell
    ("Calf Raise", "a0b9376d-c6b1-5ea9-bb64-91b11560deae"),  # Dumbbell
    ("Calf Raise", "fe005947-b93d-5c51-bdb9-9dad2a8d11bb"),  # Smith machine
]


def upgrade() -> None:
    conn = op.get_bind()

    for name_en, equipment_id in _EXERCISE_EQUIPMENT:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_equipment_map (exercise_id, equipment_id)
                SELECT e.id, :equipment_id
                FROM exercises e
                WHERE e.name_en = :name_en
                ON CONFLICT DO NOTHING
                """
            ),
            {"name_en": name_en, "equipment_id": equipment_id},
        )


def downgrade() -> None:
    conn = op.get_bind()

    equipment_ids = list({eq_id for _, eq_id in _EXERCISE_EQUIPMENT})
    conn.execute(
        sa.text(
            """
            DELETE FROM exercise_equipment_map
            WHERE equipment_id = ANY(:ids)
            """
        ),
        {"ids": equipment_ids},
    )
