"""Lexco MasterPro 브랜드를 Lexco로 통일 (DB 데이터 정정)

Revision ID: 20260528_fix_lexco_brand_unification
Revises: 20260528_seed_chancegym_gym
Create Date: 2026-05-28

배경: 20260524_seed_ai_gym_equipments 마이그레이션이 이미 실행된 후
코드만 수정되어 DB에는 Lexco MasterPro 브랜드와 해당 brand_id를
참조하는 기구 5개가 그대로 남아있음. 이 마이그레이션이 DB를 실제로 정정한다.

대상:
  - equipment_brands.id = 'df8ceb47-02dc-5e8d-aeff-fefc1ef151b6' (Lexco MasterPro) 삭제
  - equipments 5개: brand_id를 Lexco(d151cfa6-...) 로 교체
    · Hack Slide          (c86e2020-ff51-5bc5-aa6b-9440abc25ece)
    · Plate Loaded Seated Row  (38060bd0-ef8d-50a5-8953-19444f3c1056)
    · Plate Loaded Shoulder Press (5baf0161-7833-539f-8b76-6813affd32ce)
    · Plate Loaded Pulldown (3a27816b-32ff-5d43-828f-d5392f159289)
    · Seated Row           (12ef7faa-0f32-535a-80b8-dbba78d2e142)
"""

import sqlalchemy as sa
from alembic import op

revision = "20260528_fix_lexco_brand_unification"
down_revision = "20260528_seed_chancegym_gym"
branch_labels = None
depends_on = None

_LEXCO_MASTERPRO_BRAND_ID = "df8ceb47-02dc-5e8d-aeff-fefc1ef151b6"
_LEXCO_BRAND_ID = "d151cfa6-307d-5fff-acb4-8223c8db85d9"

_AFFECTED_EQUIPMENT_IDS = [
    "c86e2020-ff51-5bc5-aa6b-9440abc25ece",  # Hack Slide
    "38060bd0-ef8d-50a5-8953-19444f3c1056",  # Plate Loaded Seated Row
    "5baf0161-7833-539f-8b76-6813affd32ce",  # Plate Loaded Shoulder Press
    "3a27816b-32ff-5d43-828f-d5392f159289",  # Plate Loaded Pulldown
    "12ef7faa-0f32-535a-80b8-dbba78d2e142",  # Seated Row
]


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            "UPDATE equipments SET brand_id = :lexco WHERE brand_id = :masterpro"
        ),
        {"lexco": _LEXCO_BRAND_ID, "masterpro": _LEXCO_MASTERPRO_BRAND_ID},
    )

    conn.execute(
        sa.text("DELETE FROM equipment_brands WHERE id = :id"),
        {"id": _LEXCO_MASTERPRO_BRAND_ID},
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO equipment_brands (id, name, default_bar_unit, default_stack_unit)
            VALUES (:id, :name, :bar_unit, :stack_unit)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "id": _LEXCO_MASTERPRO_BRAND_ID,
            "name": "Lexco MasterPro",
            "bar_unit": "kg",
            "stack_unit": "kg",
        },
    )

    conn.execute(
        sa.text(
            "UPDATE equipments SET brand_id = :masterpro WHERE id = ANY(:ids)"
        ),
        {
            "masterpro": _LEXCO_MASTERPRO_BRAND_ID,
            "ids": _AFFECTED_EQUIPMENT_IDS,
        },
    )
