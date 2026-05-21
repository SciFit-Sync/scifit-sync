"""equipment_brands + equipments seed data (3사: Hammer Strength / Newtech / Panatta)

Revision ID: 20260521_seed_equipments
Revises: 008
Create Date: 2026-05-21

멱등성: ON CONFLICT (id) DO NOTHING — 중복 실행 안전
브랜드 UUID: uuid5(DNS, brand-slug) 로 결정론적 생성
"""

import csv
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260521_seed_equipments"
down_revision = "008"
branch_labels = None
depends_on = None

_SEED_CSV = Path(__file__).parent.parent.parent / "mlops" / "data" / "equipments_seed.csv"

_BRANDS = [
    {
        "id": "5a83446f-440a-5e5a-8071-f62e6244cbe6",
        "name": "Hammer Strength",
        "default_bar_unit": "lb",
        "default_stack_unit": "lb",
    },
    {
        "id": "1decce92-8e90-5ce9-94c4-d66989a4981d",
        "name": "Newtech",
        "default_bar_unit": "kg",
        "default_stack_unit": "kg",
    },
    {
        "id": "2eec52b6-35a4-57ee-8591-72283071f9e3",
        "name": "Panatta",
        "default_bar_unit": "kg",
        "default_stack_unit": "kg",
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1) 브랜드 삽입 ──
    conn.execute(
        sa.text("""
            INSERT INTO equipment_brands (id, name, default_bar_unit, default_stack_unit)
            VALUES (:id, :name, :dbu, :dsu)
            ON CONFLICT (id) DO NOTHING
        """),
        _BRANDS,
    )

    # ── 2) 기구 삽입 ──
    with open(_SEED_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    params = []
    for r in rows:
        params.append(
            {
                "id": r["id"],
                "brand_id": r["brand_id"],
                "name": r["name"],
                "name_en": r["name_en"] or None,
                "category": r["category"],
                "sub_category": r["sub_category"] or None,
                "equipment_type": r["equipment_type"],
                "pulley_ratio": float(r["pulley_ratio"]),
                "bar_weight": float(r["bar_weight"]) if r["bar_weight"] != "" else None,
                "bar_weight_unit": r["bar_weight_unit"] or None,
                "has_weight_assist": r["has_weight_assist"].lower() == "true",
                "min_stack": float(r["min_stack"]) if r["min_stack"] != "" else None,
                "max_stack": float(r["max_stack"]) if r["max_stack"] != "" else None,
                "stack_weight": r["stack_weight"] or None,
                "stack_unit": r["stack_unit"] or None,
                "image_url": r["image_url"] or None,
            }
        )

    conn.execute(
        sa.text("""
            INSERT INTO equipments (
                id, brand_id, name, name_en, category, sub_category, equipment_type,
                pulley_ratio, bar_weight, bar_weight_unit, has_weight_assist,
                min_stack, max_stack, stack_weight, stack_unit, image_url
            ) VALUES (
                :id, :brand_id, :name, :name_en, :category, :sub_category, :equipment_type,
                :pulley_ratio, :bar_weight, :bar_weight_unit, :has_weight_assist,
                :min_stack, :max_stack, :stack_weight::jsonb, :stack_unit, :image_url
            )
            ON CONFLICT (id) DO NOTHING
        """),
        params,
    )


def downgrade() -> None:
    conn = op.get_bind()
    brand_ids = [b["id"] for b in _BRANDS]
    conn.execute(
        sa.text("DELETE FROM equipments WHERE brand_id = ANY(:ids)"),
        {"ids": brand_ids},
    )
    conn.execute(
        sa.text("DELETE FROM equipment_brands WHERE id = ANY(:ids)"),
        {"ids": brand_ids},
    )
