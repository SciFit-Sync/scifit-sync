"""equipment schema v2.1+v2.2: column rename/retype, unit columns, CHECK constraints

변경 사항:
- equipment_brands: default_bar_unit, default_stack_unit 신규 (v2.1)
- equipments:
  - name_en: 003_redesign_schema에서 이미 존재 — 본 마이그레이션에서 추가 불필요
  - sub_category 신규 varchar (v2.1)
  - RENAME: bar_weight_kg -> bar_weight (v2.1)
  - RENAME: min_stack_kg -> min_stack (v2.1)
  - RENAME: max_stack_kg -> max_stack (v2.1)
  - RENAME + 타입 변경: stack_weight_kg (float) -> stack_weight (JSONB) (v2.1)
    기존 float 값은 {"value": N} 형태로 자동 변환. NULL은 NULL 유지.
  - bar_weight_unit 신규 varchar(2) (v2.1)
  - stack_unit 신규 varchar(2) (v2.1)
- CHECK 신규 (v2.1):
  - chk_bar_unit_synced: bar_weight <-> bar_weight_unit 값/단위 동기성
  - chk_stack_unit_synced: 스택 3필드 <-> stack_unit 동기성
- CHECK 신규 (v2.2):
  - chk_stack_weight_shape: stack_weight JSONB value/pattern 상호 배타

weightunit 도메인 값: 'kg' | 'lb' (native_enum=False, VARCHAR 저장)

Revision ID: 008
Revises: 007
Create Date: 2026-05-20
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1) equipment_brands: 브랜드별 기본 단위 컬럼 신규 ──
    op.add_column(
        "equipment_brands",
        sa.Column("default_bar_unit", sa.String(2), nullable=False, server_default="kg"),
    )
    op.add_column(
        "equipment_brands",
        sa.Column("default_stack_unit", sa.String(2), nullable=False, server_default="kg"),
    )

    # ── 2) equipments: 신규 컬럼 추가 ──
    # name_en은 003_redesign_schema에서 이미 생성됨
    op.add_column("equipments", sa.Column("sub_category", sa.String(50), nullable=True))
    op.add_column("equipments", sa.Column("bar_weight_unit", sa.String(2), nullable=True))
    op.add_column("equipments", sa.Column("stack_unit", sa.String(2), nullable=True))

    # ── 3) equipments: 수치 컬럼 RENAME ──
    op.alter_column("equipments", "bar_weight_kg", new_column_name="bar_weight")
    op.alter_column("equipments", "min_stack_kg", new_column_name="min_stack")
    op.alter_column("equipments", "max_stack_kg", new_column_name="max_stack")

    # ── 4) equipments: stack_weight_kg (float) RENAME 후 JSONB 타입 변환 ──
    op.alter_column("equipments", "stack_weight_kg", new_column_name="stack_weight")
    op.execute(
        """
        ALTER TABLE equipments
          ALTER COLUMN stack_weight
          TYPE jsonb
          USING CASE
            WHEN stack_weight IS NOT NULL
              THEN jsonb_build_object('value', stack_weight::numeric)
            ELSE NULL
          END
        """
    )

    # ── 5) CHECK 제약 신규 ──
    op.execute(
        """
        ALTER TABLE equipments ADD CONSTRAINT chk_bar_unit_synced CHECK (
          (bar_weight IS NULL AND bar_weight_unit IS NULL)
          OR (bar_weight IS NOT NULL AND bar_weight_unit IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE equipments ADD CONSTRAINT chk_stack_unit_synced CHECK (
          (min_stack IS NULL AND max_stack IS NULL AND stack_weight IS NULL AND stack_unit IS NULL)
          OR (
            (min_stack IS NOT NULL OR max_stack IS NOT NULL OR stack_weight IS NOT NULL)
            AND stack_unit IS NOT NULL
          )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE equipments ADD CONSTRAINT chk_stack_weight_shape CHECK (
          stack_weight IS NULL
          OR (stack_weight ? 'value' AND NOT stack_weight ? 'pattern')
          OR (stack_weight ? 'pattern' AND NOT stack_weight ? 'value')
        )
        """
    )


def downgrade() -> None:
    # ── 1) CHECK 제약 제거 ──
    op.execute("ALTER TABLE equipments DROP CONSTRAINT IF EXISTS chk_stack_weight_shape")
    op.execute("ALTER TABLE equipments DROP CONSTRAINT IF EXISTS chk_stack_unit_synced")
    op.execute("ALTER TABLE equipments DROP CONSTRAINT IF EXISTS chk_bar_unit_synced")

    # ── 2) stack_weight (JSONB) → float 복원 후 RENAME ──
    # pattern 형태는 단일 값으로 복원 불가 → NULL 처리
    op.execute(
        """
        ALTER TABLE equipments
          ALTER COLUMN stack_weight
          TYPE double precision
          USING CASE
            WHEN stack_weight IS NULL THEN NULL
            WHEN stack_weight ? 'value' THEN (stack_weight->>'value')::double precision
            ELSE NULL
          END
        """
    )
    op.alter_column("equipments", "stack_weight", new_column_name="stack_weight_kg")

    # ── 3) 수치 컬럼 RENAME 복원 ──
    op.alter_column("equipments", "bar_weight", new_column_name="bar_weight_kg")
    op.alter_column("equipments", "min_stack", new_column_name="min_stack_kg")
    op.alter_column("equipments", "max_stack", new_column_name="max_stack_kg")

    # ── 4) 신규 컬럼 제거 ──
    op.drop_column("equipments", "stack_unit")
    op.drop_column("equipments", "bar_weight_unit")
    op.drop_column("equipments", "sub_category")
    op.drop_column("equipment_brands", "default_stack_unit")
    op.drop_column("equipment_brands", "default_bar_unit")
