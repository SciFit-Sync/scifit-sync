"""정합성 복구: prod 누락 default_equipment_id + bodyweight 보강 (forward-only 멱등)

Revision ID: 20260605_recover_default_equip
Revises: 20260604_chancegym_salus2
Create Date: 2026-06-05

배경 (마이그레이션 드리프트):
  멀티헤드 재정렬(PR #272/#274) 후유증으로 prod alembic_version=fix_muscle_name_ko 가
  두 미적용 조상 마이그레이션(20260604_bodyweight_seed, 20260604_ex_default_equip)보다
  체인상 '위'(자손)에 안착했다. alembic은 prod head가 그 조상들도 적용했다고 간주하므로
  `alembic upgrade head` 로는 두 마이그레이션이 영원히 실행되지 않는 divergent 상태다.

  prod 실측(2026-06-05, read-only):
    - exercises.default_equipment_id 컬럼 없음 (ex_default_equip 미적용)
    - equipment_type='bodyweight' 기구 0개 (bodyweight_seed 미적용)
    - 적용됨: rex_display_name / rex_equip_notnull(equipment_id NOT NULL) /
      seed_machine_movement_templates(movement_label_en) / eqmuscle_direct
  영향: develop 런타임(routines.py / gyms.py)이 Exercise.default_equipment_id 를 무조건
  JOIN/SELECT → gym 선택 루틴 생성·프리웨이트 RAG 후보·기구 대체가 'column does not exist'
  로 500 크래시. 즉 develop 배포의 선결 블로커.

해결 (이 마이그레이션):
  원본 ex_default_equip / bodyweight_seed 의 down_revision 은 절대 손대지 않는다(이미 적용된
  clean DB 의 alembic_version 정합성을 깨므로). 대신 두 효과를 전부 멱등 가드로 '재적용'한다.
  down_revision 을 repo 단일 head(chancegym_salus2)에 매달아 멀티헤드를 만들지 않는다.
    - prod: fix_muscle_name_ko → chancegym_salus2 → (본 복구분) 순으로 forward 진행하며 보강.
    - clean DB(CI/로컬): 이미 두 원본이 정상 적용된 상태라 전 스텝이 no-op.

스텝 순서(의존): ① 컬럼 추가 → ② generic Bodyweight 기구 → ③ bodyweight 운동 eem
  → ④ routine_exercises.equipment_id 백필(M4만, NOT NULL 승격/FK 재생성 = M5 는 절대 미포함,
     prod 에 이미 적용됨) → ⑤ exercises.default_equipment_id 백필.
  ②③ 이 ④⑤ 보다 먼저여야 bodyweight 경로가 채워진다. is_freeweight 는 GENERATED STORED 라
  generic Bodyweight(type='bodyweight')가 자동 true → ⑤(WHERE is_freeweight=true)가 포착.

배포 순서(코드 아닌 운영 통제):
  - 본 마이그레이션이 prod 에 적용 완료된 뒤에만 develop 런타임을 배포한다(alembic upgrade 선행).
  - PR-5(exercise_equipment_map DROP)는 본 마이그레이션보다 반드시 후행(②③④⑤가 eem 의존).

asyncpg 안전: named param + CAST(:p AS uuid)만, ANY(:list)/:p::uuid 회피. 운동 목록은 단건 루프.
downgrade 는 no-op — 컬럼/기구/eem/백필 원복은 ex_default_equip / bodyweight_seed 원본
downgrade 가 소유하므로 본 복구분이 DROP 하면 이중 소유로 정합성이 깨진다.
"""

import uuid as _uuid

import sqlalchemy as sa
from alembic import op

revision = "20260605_recover_default_equip"
down_revision = "20260604_chancegym_salus2"
branch_labels = None
depends_on = None

# bodyweight_seed 와 동일한 결정론 UUID (반드시 일치 — 1글자라도 다르면 중복 기구 생성).
_BODYWEIGHT_UUID = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, "scifit-sync.equipment.bodyweight-generic"))

# bodyweight_seed 와 동일 목록. 단건 name_en 매칭 → 미존재분 자동 skip.
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

    # ① exercises.default_equipment_id (nullable FK, ON DELETE SET NULL).
    #    ADD COLUMN IF NOT EXISTS 가 컬럼+인라인 FK 전체를 원자적으로 건너뛰므로
    #    clean DB(컬럼 존재)에선 'constraint already exists' 없이 통째 skip. 원본 ex_default_equip 과 동일.
    op.execute(
        "ALTER TABLE exercises ADD COLUMN IF NOT EXISTS default_equipment_id uuid "
        "REFERENCES equipments (id) ON DELETE SET NULL"
    )

    # ② generic Bodyweight 기구 (멱등: PK 충돌 무시). 원본 bodyweight_seed 와 동일 컬럼/값.
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

    # ③ bodyweight 운동 eem (단건 루프, 미존재 운동은 SELECT 0행 → skip). 원본 bodyweight_seed 와 동일.
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

    # ④ routine_exercises.equipment_id 백필 (rex_equip_notnull M4 ranked SQL 그대로, NULL 행만).
    #    ★ M5(FK 재생성 / VALIDATE / SET NOT NULL)는 절대 포함하지 않는다 — prod 에 이미 적용돼 있어
    #      복붙 시 'constraint already exists' / 불필요한 풀스캔 락 발생. prod·clean 모두 사실상 no-op.
    op.execute(
        """
        WITH ranked AS (
            SELECT re.id AS rex_id,
                   e.id  AS equipment_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY re.id
                       ORDER BY
                           CASE
                               WHEN ge.equipment_id IS NOT NULL THEN 0  -- 루틴 헬스장 머신
                               WHEN e.is_freeweight THEN 1              -- 공통 프리웨이트
                               ELSE 2                                   -- 그 외(정렬상 최후)
                           END,
                           e.id
                   ) AS rn
            FROM routine_exercises re
            JOIN routine_days rd        ON rd.id = re.routine_day_id
            JOIN workout_routines wr    ON wr.id = rd.routine_id
            JOIN exercise_equipment_map eem ON eem.exercise_id = re.exercise_id
            JOIN equipments e           ON e.id = eem.equipment_id
            LEFT JOIN gym_equipments ge ON ge.equipment_id = e.id AND ge.gym_id = wr.gym_id
            WHERE re.equipment_id IS NULL
        )
        UPDATE routine_exercises re
        SET equipment_id = ranked.equipment_id
        FROM ranked
        WHERE ranked.rex_id = re.id AND ranked.rn = 1
        """
    )

    # ④ 가드: prod 에는 equipment_id NOT NULL 이 이미 걸려 있어 잔존 NULL 은 이론상 불가.
    #    그래도 안전망으로 카운트 — NULL 이 남으면(eem 미매핑) 진행 보류(silent 진행 방지).
    remaining = conn.execute(sa.text("SELECT count(*) FROM routine_exercises WHERE equipment_id IS NULL")).scalar_one()
    if remaining and int(remaining) > 0:
        raise RuntimeError(f"routine_exercises.equipment_id NULL {remaining}건 — eem 매핑 누락. 수동 확인 필요.")

    # ⑤ exercises.default_equipment_id 백필 (ex_default_equip 와 동일, NULL 행만 — clean DB 기존값 보호).
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
          AND ex.default_equipment_id IS NULL
        """
    )


def downgrade() -> None:
    # no-op: 컬럼/기구/eem/백필 원복은 ex_default_equip · bodyweight_seed 원본 downgrade 가 소유한다.
    # 본 복구분이 DROP 하면 이중 소유로 정합성이 깨지므로 의도적으로 아무것도 하지 않는다
    # (eqmuscle_direct 와 동일 패턴).
    pass
