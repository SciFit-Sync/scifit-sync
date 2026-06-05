"""찬스짐 Salus 기구 2개 추가 (SAF012 Standing Shoulder Press + Multi Linear Row)

Revision ID: 20260604_chancegym_salus2
Revises: 20260604_fix_muscle_name_ko
Create Date: 2026-06-04

배경:
  더찬스짐(kakao_place_id=1875030524)에 SALUS 신규 plate-loaded 기구 2개 추가.
  기존 찬스짐 기구 33개(20260527/20260528)와 동일한 입력 형식·UUID 규칙.

  ① SAF012 Standing Shoulder Press (스탠딩 숄더프레스 + 승모타겟, 원판)
     SALUS 공식 모델 SAF012. category=shoulders / sub_category=front_delt.
     movement_label "Machine Shoulder Press" → 전면삼각근 자동도출.
  ② Multi Linear Row (SALUS 멀티 리니어 로우, 원판)
     별칭 T-Bar Row / Linear Row — 별칭 컬럼이 없어 정식명만 name 에 저장.
     category=back / sub_category=upper_back.
     movement_label "Machine Row" → 능형근 자동도출
     (기존 Salus "Linear Row / Assisted T-Bar Row" 와 동일 매핑).

레이어 (기구 1개 = 3 테이블):
  1. equipments       — 2행 INSERT (movement_label 포함, plate-loaded 패턴)
  2. gym_equipments   — 더찬스짐 매핑 2행 (kakao_place_id 로 gym_id 조회, fallback)
  3. equipment_muscles — movement_label_en → exercises.name_en JOIN 으로 근육 자동도출.
     20260604_eqmuscle_direct 는 이미 실행돼 신규 행엔 재적용되지 않으므로 동일
     로직을 신규 2개에 한정해 여기서 replay 한다.

plate-loaded 패턴(기존 "Plate Loaded …" 행과 동일):
  equipment_type='machine', pulley_ratio=1, bar_weight=NULL/bar_weight_unit=NULL,
  has_weight_assist=false, min_stack=0, max_stack=120, stack_weight={"value":5}, stack_unit='kg'.

UUID: uuid5(NAMESPACE_DNS, "scifit-chancegym-{name}-{brand}") — 기존 찬스짐과 동일.
멱등성: 전 구간 ON CONFLICT DO NOTHING.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_chancegym_salus2"
down_revision = "20260604_fix_muscle_name_ko"
branch_labels = None
depends_on = None

_SALUS_BRAND_ID = "6dc8a99d-5fe9-5736-9704-e8820d9805b3"
_KAKAO_PLACE_ID = "1875030524"
_GYM_ID_FALLBACK = "ecdd073b-f894-5c5a-86cc-a9b42a4e6985"

# (id, name(=name_en), category, sub_category, movement_label_ko, movement_label_en)
_EQUIPMENTS = [
    (
        "8420631d-e82e-5b73-8d15-d957c90b4254",
        "SAF012 Standing Shoulder Press",
        "shoulders",
        "front_delt",
        "머신 숄더 프레스",
        "Machine Shoulder Press",
    ),
    (
        "6d072212-c936-5af1-8dc5-6f05a5deb1b2",
        "Multi Linear Row",
        "back",
        "upper_back",
        "머신 로우",
        "Machine Row",
    ),
]

# id 스코프는 리터럴 IN 으로 (드라이버 배열 파라미터 의존 회피)
_IDS_SQL = ", ".join(f"'{row[0]}'" for row in _EQUIPMENTS)


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. equipments (plate-loaded 머신) ────────────────────────────────────
    conn.execute(
        sa.text("""
            INSERT INTO equipments (
                id, brand_id, name, name_en, category, sub_category,
                equipment_type, pulley_ratio, bar_weight, bar_weight_unit,
                has_weight_assist, min_stack, max_stack, stack_weight, stack_unit,
                movement_label_ko, movement_label_en
            ) VALUES (
                :id, :brand_id, :name, :name, :category, :sub_category,
                'machine', 1.0, NULL, NULL,
                false, 0.0, 120.0, CAST('{"value": 5.0}' AS jsonb), 'kg',
                :label_ko, :label_en
            )
            ON CONFLICT DO NOTHING
        """),
        [
            {
                "id": r[0],
                "brand_id": _SALUS_BRAND_ID,
                "name": r[1],
                "category": r[2],
                "sub_category": r[3],
                "label_ko": r[4],
                "label_en": r[5],
            }
            for r in _EQUIPMENTS
        ],
    )

    # ── 2. gym_equipments (더찬스짐) ──────────────────────────────────────────
    # kakao_place_id 로 실제 gym_id 조회 (createGym API 등록분과 UUID 다를 수 있음), 없으면 fallback
    row = conn.execute(
        sa.text("SELECT id FROM gyms WHERE kakao_place_id = :kpid"),
        {"kpid": _KAKAO_PLACE_ID},
    ).fetchone()
    gym_id = str(row[0]) if row else _GYM_ID_FALLBACK

    conn.execute(
        sa.text("""
            INSERT INTO gym_equipments (gym_id, equipment_id, quantity)
            VALUES (:gym_id, :equipment_id, 1)
            ON CONFLICT DO NOTHING
        """),
        [{"gym_id": gym_id, "equipment_id": r[0]} for r in _EQUIPMENTS],
    )

    # ── 3. equipment_muscles — movement_label_en → exercises.name_en 자동도출 ──
    # 20260604_eqmuscle_direct 와 동일 로직, 신규 2개 한정 replay.
    # DISTINCT ON + ORDER BY 로 (equipment_id, muscle_group_id)당 1행 결정론 선택.
    conn.execute(
        sa.text(f"""
            INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement, activation_pct)
            SELECT DISTINCT ON (e.id, xm.muscle_group_id)
                e.id, xm.muscle_group_id, xm.involvement, xm.activation_pct
            FROM equipments e
            JOIN exercises ex ON lower(ex.name_en) = lower(e.movement_label_en)
            JOIN exercise_muscles xm ON xm.exercise_id = ex.id
            WHERE e.id IN ({_IDS_SQL})
              AND e.movement_label_en IS NOT NULL
            ORDER BY
                e.id, xm.muscle_group_id,
                (xm.involvement = 'primary') DESC,
                xm.activation_pct DESC NULLS LAST
            ON CONFLICT DO NOTHING
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    # FK 순서: 자식(equipment_muscles / gym_equipments) → 부모(equipments)
    conn.execute(sa.text(f"DELETE FROM equipment_muscles WHERE equipment_id IN ({_IDS_SQL})"))
    conn.execute(sa.text(f"DELETE FROM gym_equipments WHERE equipment_id IN ({_IDS_SQL})"))
    conn.execute(sa.text(f"DELETE FROM equipments WHERE id IN ({_IDS_SQL})"))
