"""fix: seed.py와 alembic 마이그레이션 간 중복 muscle_group 항목 통합

Revision ID: 20260603_dedup_muscles
Revises: 20260529_fix_panatta_image_url
Create Date: 2026-06-03

배경:
  seed.py(구어체 한국어)와 20260525_seed_muscle_groups_exercises(해부학 명칭)가
  같은 근육에 대해 각각 별도 muscle_group 행을 생성해 다음 버그 발생:
    1. 근육활성도 카드에 "가슴"+"대흉근", "어깨 전면"+"전면 삼각근" 등이 각각 표시
    2. 루틴 생성 시 target_muscle_group_ids 선택 결과가 어느 그룹 ID냐에 따라 상이

중복 쌍:
  seed.py name_ko  | alembic name (slug)  | 통합 후 name_ko
  ─────────────────────────────────────────────────────────
  가슴              | pectoralis_major      | 가슴
  어깨 전면          | anterior_deltoid      | 어깨 전면
  어깨 측면          | lateral_deltoid       | 어깨 측면
  어깨 후면          | posterior_deltoid     | 어깨 후면
  둔근              | gluteus_maximus       | 둔근
  복근              | rectus_abdominis      | 복근

수정 전략:
  1. alembic 그룹(해부학 slug 보유)을 정본으로 유지
  2. exercise_muscles / equipment_muscles 를 seed.py 그룹 → alembic 그룹으로 이관
     (ON CONFLICT DO NOTHING — 이미 alembic이 직접 삽입한 행은 skip)
  3. workout_routines.target_muscle_group_ids JSONB 배열 내 seed.py UUID를 alembic UUID로 교체
  4. seed.py 중복 그룹 DELETE
  5. alembic 그룹의 name_ko를 사용자 친화적 구어체로 UPDATE
"""

import sqlalchemy as sa
from alembic import op

revision = "20260603_dedup_muscles"
down_revision = "20260529_fix_panatta_image_url"
branch_labels = None
depends_on = None

# (seed_py_name_ko, alembic_slug, new_name_ko)
_PAIRS = [
    ("가슴", "pectoralis_major", "가슴"),
    ("어깨 전면", "anterior_deltoid", "어깨 전면"),
    ("어깨 측면", "lateral_deltoid", "어깨 측면"),
    ("어깨 후면", "posterior_deltoid", "어깨 후면"),
    ("둔근", "gluteus_maximus", "둔근"),
    ("복근", "rectus_abdominis", "복근"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for seed_name_ko, alembic_slug, new_name_ko in _PAIRS:
        # seed.py 그룹: name_ko = seed_name_ko, name ≠ alembic_slug
        seed_row = conn.execute(
            sa.text("SELECT id FROM muscle_groups WHERE name_ko = :nko AND name != :slug"),
            {"nko": seed_name_ko, "slug": alembic_slug},
        ).fetchone()

        alembic_row = conn.execute(
            sa.text("SELECT id FROM muscle_groups WHERE name = :slug"),
            {"slug": alembic_slug},
        ).fetchone()

        if seed_row is None or alembic_row is None:
            # 둘 중 하나가 없으면 이미 정리됐거나 다른 상태 — skip
            continue

        seed_id = str(seed_row[0])
        alembic_id = str(alembic_row[0])

        # ── 1. exercise_muscles 이관 ─────────────────────────────────────────
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_muscles (exercise_id, muscle_group_id, involvement, activation_pct)
                SELECT exercise_id, CAST(:alembic_id AS uuid), involvement, activation_pct
                FROM exercise_muscles
                WHERE muscle_group_id = CAST(:seed_id AS uuid)
                ON CONFLICT DO NOTHING
                """
            ),
            {"alembic_id": alembic_id, "seed_id": seed_id},
        )
        conn.execute(
            sa.text("DELETE FROM exercise_muscles WHERE muscle_group_id = CAST(:seed_id AS uuid)"),
            {"seed_id": seed_id},
        )

        # ── 2. equipment_muscles 이관 ────────────────────────────────────────
        conn.execute(
            sa.text(
                """
                INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement)
                SELECT equipment_id, CAST(:alembic_id AS uuid), involvement
                FROM equipment_muscles
                WHERE muscle_group_id = CAST(:seed_id AS uuid)
                ON CONFLICT DO NOTHING
                """
            ),
            {"alembic_id": alembic_id, "seed_id": seed_id},
        )
        conn.execute(
            sa.text("DELETE FROM equipment_muscles WHERE muscle_group_id = CAST(:seed_id AS uuid)"),
            {"seed_id": seed_id},
        )

        # ── 3. workout_routines.target_muscle_group_ids JSONB 배열 교체 ─────
        # JSONB 배열 원소 중 seed_id(문자열) → alembic_id(문자열) 치환
        conn.execute(
            sa.text(
                """
                UPDATE workout_routines
                SET target_muscle_group_ids = (
                    SELECT jsonb_agg(
                        CASE WHEN elem = to_jsonb(CAST(:seed_id AS text))
                             THEN to_jsonb(CAST(:alembic_id AS text))
                             ELSE elem
                        END
                    )
                    FROM jsonb_array_elements(target_muscle_group_ids) AS elem
                )
                WHERE target_muscle_group_ids IS NOT NULL
                  AND target_muscle_group_ids @> to_jsonb(CAST(:seed_id AS text))
                """
            ),
            {"seed_id": seed_id, "alembic_id": alembic_id},
        )

        # ── 4. seed.py 중복 그룹 삭제 ────────────────────────────────────────
        conn.execute(
            sa.text("DELETE FROM muscle_groups WHERE id = CAST(:seed_id AS uuid)"),
            {"seed_id": seed_id},
        )

        # ── 5. alembic 그룹 name_ko 사용자 친화적으로 변경 ───────────────────
        conn.execute(
            sa.text("UPDATE muscle_groups SET name_ko = :new_nko WHERE name = :slug"),
            {"new_nko": new_name_ko, "slug": alembic_slug},
        )


def downgrade() -> None:
    # 롤백 시 seed.py 그룹을 복구하고 exercise_muscles를 원복하는 것은
    # 데이터 손실 없이 역방향 재현이 어려우므로 지원하지 않음.
    # 필요 시 스냅샷/백업에서 복구할 것.
    raise NotImplementedError("downgrade not supported — restore from backup if needed")
