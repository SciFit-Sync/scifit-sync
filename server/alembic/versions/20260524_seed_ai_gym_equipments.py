"""AI팀 제공 헬스장 머신 22개 seed (브랜드 6개 포함)

Revision ID: 20260524_seed_ai_gym_equipments
Revises: 20260521_seed_equipments
Create Date: 2026-05-24

멱등성: ON CONFLICT DO NOTHING — brand name UNIQUE / equipment id UNIQUE 충돌 모두 skip.
UUID: uuid5(NAMESPACE_DNS, "scifit-brand-{slug}") / "scifit-ai-eq-{n}" 결정론적 생성.
브랜드 통합: Lexco Master → Lexco (같은 제조사, 제품 라인 차이)
"""

import sqlalchemy as sa
from alembic import op

revision = "20260524_seed_ai_gym_equipments"
down_revision = "20260521_seed_equipments"
branch_labels = None
depends_on = None

# ── 브랜드 6개 ────────────────────────────────────────────────────────────────
_BRANDS = [
    # (id, name, default_bar_unit, default_stack_unit)
    ("ae5eaca3-7a8c-5957-99db-a902ba8acc5b", "Gym80", "kg", "kg"),
    ("00450d91-d251-5353-a003-0e1ca6adcc43", "NEM", "kg", "kg"),
    ("df8ceb47-02dc-5e8d-aeff-fefc1ef151b6", "Lexco MasterPro", "kg", "kg"),
    ("c0802a7e-b07a-5bcb-826a-ef45a8188a7c", "Booty Builder", "kg", "kg"),
    ("6dc8a99d-5fe9-5736-9704-e8820d9805b3", "Salus", "kg", "kg"),
    ("d151cfa6-307d-5fff-acb4-8223c8db85d9", "Lexco", "kg", "kg"),
]

# ── 기구 22개 ─────────────────────────────────────────────────────────────────
# 컬럼: id, brand_id, name, name_en, category, sub_category,
#        equipment_type, pulley_ratio, bar_weight, bar_weight_unit,
#        has_weight_assist, min_stack, max_stack, stack_weight, stack_unit
#
# 분류 기준:
#   plate-loaded → bar_weight_unit='kg', stack_* = None
#   selectorized  → stack_unit='kg',     bar_weight* = None
#   cable         → stack_unit='kg',     equipment_type='cable'
_EQUIPMENTS = [
    # 1 Preacher Curl — Gym80 — plate-loaded
    (
        "19a54688-5738-5772-bdc0-8e8e9b00ffa0",
        "ae5eaca3-7a8c-5957-99db-a902ba8acc5b",
        "Preacher Curl",
        "Preacher Curl",
        "arms",
        "biceps",
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 2 Leg Press — NEM — selectorized
    (
        "c7f4d762-0959-525f-ba74-41f31f4c97a2",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Leg Press",
        "Leg Press",
        "legs",
        "quads",
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 3 Hack Squat — Gym80 — plate-loaded
    (
        "24d1fdc2-e16d-58fc-b190-6a9c63791ed2",
        "ae5eaca3-7a8c-5957-99db-a902ba8acc5b",
        "Hack Squat",
        "Hack Squat",
        "legs",
        "quads",
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 4 Hack Slide — Lexco MasterPro — plate-loaded
    (
        "c86e2020-ff51-5bc5-aa6b-9440abc25ece",
        "df8ceb47-02dc-5e8d-aeff-fefc1ef151b6",
        "Hack Slide",
        "Hack Slide",
        "legs",
        "quads",
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 5 Plate Loaded Incline Press — Lexco — plate-loaded
    (
        "e75243ad-f9b5-5690-a0df-d6e1c4e0706a",
        "d151cfa6-307d-5fff-acb4-8223c8db85d9",
        "Plate Loaded Incline Press",
        "Incline Chest Press",
        "chest",
        "upper_chest",
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 6 Lat Pulldown — NEM — selectorized
    (
        "e30fec2a-4f2f-5be9-be60-11f37635db30",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Lat Pulldown",
        "Lat Pulldown",
        "back",
        None,
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 7 Shoulder Press — NEM — selectorized
    (
        "db822805-d18f-5fab-940f-ee0dfb593de0",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Shoulder Press",
        "Shoulder Press",
        "shoulders",
        "front_delt",
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 8 Chest Press — NEM — selectorized
    (
        "c372857c-526d-51e2-9e4d-4e59f345bf41",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Chest Press",
        "Chest Press",
        "chest",
        None,
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 9 Incline Press — NEM — selectorized
    (
        "c0633411-a338-566e-ae55-19e4a6109bc4",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Incline Press",
        "Incline Chest Press",
        "chest",
        "upper_chest",
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 10 Plate Loaded Seated Row — Lexco MasterPro — plate-loaded
    (
        "38060bd0-ef8d-50a5-8953-19444f3c1056",
        "df8ceb47-02dc-5e8d-aeff-fefc1ef151b6",
        "Plate Loaded Seated Row",
        "Seated Row",
        "back",
        None,
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 11 Plate Loaded Shoulder Press — Lexco MasterPro — plate-loaded
    (
        "5baf0161-7833-539f-8b76-6813affd32ce",
        "df8ceb47-02dc-5e8d-aeff-fefc1ef151b6",
        "Plate Loaded Shoulder Press",
        "Shoulder Press",
        "shoulders",
        None,
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 12 Hip Thrust Machine — Booty Builder — selectorized
    (
        "3cf2a5f4-f44f-5579-b0cc-990f4dac5eaa",
        "c0802a7e-b07a-5bcb-826a-ef45a8188a7c",
        "Hip Thrust Machine",
        "Hip Thrust",
        "legs",
        "glutes",
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 13 M-Torture Front Row — NEM — plate-loaded
    (
        "9cc2c57c-e7cc-52c0-860f-238a92730de2",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "M-Torture Front Row",
        "Front Row",
        "back",
        None,
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 14 Plate Loaded Pulldown — Lexco MasterPro — plate-loaded
    (
        "3a27816b-32ff-5d43-828f-d5392f159289",
        "df8ceb47-02dc-5e8d-aeff-fefc1ef151b6",
        "Plate Loaded Pulldown",
        "Lat Pulldown",
        "back",
        None,
        "machine",
        1.0,
        None,
        "kg",
        False,
        None,
        None,
        None,
        None,
    ),
    # 15 Assisted T-Bar Row — Salus — selectorized
    (
        "06d73bb4-7fce-51b6-ad03-e877eb6aaaf4",
        "6dc8a99d-5fe9-5736-9704-e8820d9805b3",
        "Assisted T-Bar Row",
        "T-Bar Row",
        "back",
        None,
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 16 Seated Leg Press — NEM — selectorized
    (
        "f74c9291-3a84-50df-8098-1ec1faf08962",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Seated Leg Press",
        "Leg Press",
        "legs",
        "quads",
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 17 Seated Cable Row — NEM — cable selectorized
    (
        "c57308c4-4d86-5468-b306-5d946b33b5de",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Seated Cable Row",
        "Seated Cable Row",
        "back",
        None,
        "cable",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 18 Seated Row — Lexco MasterPro — selectorized
    (
        "12ef7faa-0f32-535a-80b8-dbba78d2e142",
        "df8ceb47-02dc-5e8d-aeff-fefc1ef151b6",
        "Seated Row",
        "Seated Row",
        "back",
        None,
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 19 Lat Pulldown — Lexco — selectorized
    (
        "6fa72444-be8d-5d28-89bd-56764f5cc636",
        "d151cfa6-307d-5fff-acb4-8223c8db85d9",
        "Lat Pulldown",
        "Lat Pulldown",
        "back",
        None,
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 20 Assisted Dip/Chin — NEM — selectorized (has_weight_assist=True)
    (
        "63e8d4bf-0c6f-59de-9a32-4c816d05cbf2",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Assisted Dip/Chin",
        "Assisted Dip",
        "chest",
        None,
        "machine",
        1.0,
        None,
        None,
        True,
        None,
        None,
        None,
        "kg",
    ),
    # 21 Pectoral Fly / Rear Deltoid — NEM — selectorized
    (
        "2fa87cc3-c055-5b87-b901-2c7d4baa3d33",
        "00450d91-d251-5353-a003-0e1ca6adcc43",
        "Pectoral Fly / Rear Deltoid",
        "Pec Fly",
        "chest",
        None,
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
    # 22 Pec Fly / Rear Delt — Lexco — selectorized
    (
        "7b799749-d16a-5245-b9ca-c10489bdf59e",
        "d151cfa6-307d-5fff-acb4-8223c8db85d9",
        "Pec Fly / Rear Delt",
        "Pec Fly",
        "chest",
        "rear_delt",
        "machine",
        1.0,
        None,
        None,
        False,
        None,
        None,
        None,
        "kg",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1) 브랜드 삽입 ──
    conn.execute(
        sa.text("""
            INSERT INTO equipment_brands (id, name, default_bar_unit, default_stack_unit)
            VALUES (:id, :name, :bar, :stack)
            ON CONFLICT DO NOTHING
        """),
        [{"id": b[0], "name": b[1], "bar": b[2], "stack": b[3]} for b in _BRANDS],
    )

    # ── 2) 기구 삽입 ──
    params = [
        {
            "id": row[0],
            "brand_id": row[1],
            "name": row[2],
            "name_en": row[3],
            "category": row[4],
            "sub_category": row[5],
            "equipment_type": row[6],
            "pulley_ratio": row[7],
            "bar_weight": row[8],
            "bar_weight_unit": row[9],
            "has_weight_assist": row[10],
            "min_stack": row[11],
            "max_stack": row[12],
            "stack_weight": row[13],
            "stack_unit": row[14],
        }
        for row in _EQUIPMENTS
    ]

    conn.execute(
        sa.text("""
            INSERT INTO equipments (
                id, brand_id, name, name_en, category, sub_category,
                equipment_type, pulley_ratio, bar_weight, bar_weight_unit,
                has_weight_assist, min_stack, max_stack,
                stack_weight, stack_unit
            ) VALUES (
                :id, :brand_id, :name, :name_en, :category, :sub_category,
                :equipment_type, :pulley_ratio, :bar_weight, :bar_weight_unit,
                :has_weight_assist, :min_stack, :max_stack,
                CAST(:stack_weight AS jsonb), :stack_unit
            )
            ON CONFLICT DO NOTHING
        """),
        params,
    )


def downgrade() -> None:
    conn = op.get_bind()
    eq_ids = [row[0] for row in _EQUIPMENTS]
    brand_ids = [b[0] for b in _BRANDS]
    conn.execute(
        sa.text("DELETE FROM equipments WHERE id = ANY(:ids)"),
        {"ids": eq_ids},
    )
    conn.execute(
        sa.text("DELETE FROM equipment_brands WHERE id = ANY(:ids)"),
        {"ids": brand_ids},
    )
