"""bodyweight 운동 기구 매핑 — generic bodyweight equipment + eem + default_equipment_id

Revision ID: 20260604_bodyweight_seed
Revises: 20260604_rex_display_name
Create Date: 2026-06-04

배경:
  seed_freeweight_exercises가 bodyweight 8개(Dips/Push Up/Pull Up/Crunch/Hanging Leg
  Raise/Plank/Russian Twist/Lying Leg Raise)를 제외해, 이 운동들은 exercises(20260525
  시드)에 존재하나 default_equipment_id·exercise_equipment_map 매핑이 없다. 결과:
   - rex_equip_notnull(PR-4) 백필이 이 운동을 쓰는 기존 루틴을 못 채워 NOT NULL 승격이
     중단(prod 실측: Plank×3/Crunch/Ab Rollout = 5행).
   - 루틴 생성 프리 후보(_build_rag_profile, is_freeweight=true)에도 안 나옴.

변경:
  generic 'Bodyweight' 기구 1개(equipment_type='bodyweight' → is_freeweight=true)를 만들고
  bodyweight 운동에 exercise_equipment_map + exercises.default_equipment_id를 연결한다.
  → rex_equip_notnull 백필이 eem 경로로 채우고, _build_rag_profile 프리 후보에 자동 포함.

체인 위치 (중요):
  rex_equip_notnull(NOT NULL 승격)보다 **먼저** 실행돼야 prod 5행이 백필되므로
  down_revision = rex_display_name 으로 두고, rex_equip_notnull.down_revision을 본 revision
  으로 재지정한다 (rex_display_name ← bodyweight_seed ← rex_equip_notnull).

  Ab Rollout은 develop 마이그레이션엔 없으나 prod엔 존재(과거 수동 시드 추정). name_en
  단건 매칭이라 prod에선 매핑되고 develop/CI엔 없어 무해(skip).

asyncpg 안전:
  dedup_muscles 인시던트 교훈 — 단순 named 파라미터 + CAST(:p AS uuid)만 사용
  (`:p::uuid`/`ANY(:list)` 회피). 운동 목록은 Python 루프로 단건 실행.
"""

import uuid as _uuid

import sqlalchemy as sa
from alembic import op

revision = "20260604_bodyweight_seed"
down_revision = "20260604_rex_display_name"
branch_labels = None
depends_on = None

# 결정론 generic bodyweight 기구 UUID (uuid5 — 재실행/환경 무관 고정값)
_BODYWEIGHT_UUID = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, "scifit-sync.equipment.bodyweight-generic"))

# seed_freeweight 제외 8개 + Ab Rollout(prod 존재). 단건 name_en 매칭 → 미존재분 자동 skip.
_BODYWEIGHT_EXERCISES = [
    "Dips",
    "Push Up",
    "Pull Up",
    "Crunch",
    "Hanging Leg Raise",
    "Plank",
    "Russian Twist",
    "Lying Leg Raise",
    "Ab Rollout",
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. generic bodyweight 기구 (멱등)
    conn.execute(
        sa.text(
            """
            INSERT INTO equipments (id, name, name_en, equipment_type, pulley_ratio, updated_at)
            VALUES (CAST(:id AS uuid), '맨몸', 'Bodyweight', 'bodyweight', 1.0, now())
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": _BODYWEIGHT_UUID},
    )

    # 2~3. 운동별: eem 매핑(rex_equip_notnull 백필 경로) + default_equipment_id(런타임 프리 후보)
    for name_en in _BODYWEIGHT_EXERCISES:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_equipment_map (exercise_id, equipment_id)
                SELECT ex.id, CAST(:bw AS uuid)
                FROM exercises ex
                WHERE ex.name_en = :nm
                ON CONFLICT DO NOTHING
                """
            ),
            {"bw": _BODYWEIGHT_UUID, "nm": name_en},
        )
        conn.execute(
            sa.text(
                """
                UPDATE exercises
                SET default_equipment_id = CAST(:bw AS uuid)
                WHERE name_en = :nm AND default_equipment_id IS NULL
                """
            ),
            {"bw": _BODYWEIGHT_UUID, "nm": name_en},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # 역순(이 revision이 넣은 것만): default 해제 → eem 삭제 → 기구 삭제
    conn.execute(
        sa.text("UPDATE exercises SET default_equipment_id = NULL WHERE default_equipment_id = CAST(:bw AS uuid)"),
        {"bw": _BODYWEIGHT_UUID},
    )
    conn.execute(
        sa.text("DELETE FROM exercise_equipment_map WHERE equipment_id = CAST(:bw AS uuid)"),
        {"bw": _BODYWEIGHT_UUID},
    )
    conn.execute(sa.text("DELETE FROM equipments WHERE id = CAST(:bw AS uuid)"), {"bw": _BODYWEIGHT_UUID})
