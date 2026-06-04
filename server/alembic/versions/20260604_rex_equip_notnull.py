"""routine_exercises.equipment_id 백필 + NOT NULL/RESTRICT 승격 (기구-중심 PR-4: M4+M5)

Revision ID: 20260604_rex_equip_notnull
Revises: 20260604_rex_display_name
Create Date: 2026-06-04

기구-중심 재설계의 마지막 비파괴 단계. equipment_id를 routine_exercises의 1차 단위로
격상한다(스펙 §2-3, §5 M4/M5).

M4 (백필): equipment_id IS NULL 행을 (루틴 gym_id, exercise_id) 기준으로 결정론적으로 채운다.
  우선순위: 1) 루틴 헬스장에 등록된 머신  2) 전 헬스장 공통 프리웨이트  3) (정렬상) 임의 1개.
  exercise→equipment 후보는 exercise_equipment_map(폐기 예정, M5에서 DROP)에서 얻는다.
  백필 후에도 NULL이 남으면(해당 exercise가 어떤 equipment에도 매핑 안 됨) 승격을 중단(raise)한다.

M5 (승격): FK ondelete SET NULL → RESTRICT(NOT VALID→VALIDATE 2단계) + 컬럼 SET NOT NULL.

downgrade는 비파괴: 제약만 원복하고 백필된 값은 되돌리지 않는다(데이터 손실 방지).
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_rex_equip_notnull"
down_revision = "20260604_rex_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── M4: equipment_id NULL 행 결정론적 백필 ──
    # ROW_NUMBER로 행마다 우선순위 1위 기구 1개 선택(결정론: 우선순위 → equipment id 정렬).
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

    # ── 가드: 백필 후에도 NULL 잔존 시 승격 보류(스펙 §5 M4) ──
    remaining = conn.execute(sa.text("SELECT count(*) FROM routine_exercises WHERE equipment_id IS NULL")).scalar_one()
    if remaining and int(remaining) > 0:
        raise RuntimeError(
            f"routine_exercises.equipment_id NULL {remaining}건이 백필되지 않아 "
            "NOT NULL 승격을 중단합니다. 해당 행의 exercise_id가 exercise_equipment_map에 "
            "매핑돼 있는지 확인 후 수동 처리하세요."
        )

    # ── M5: NOT NULL/RESTRICT 승격 ──
    op.execute("SET lock_timeout = '5s'")

    # 기존 FK(ondelete=SET NULL) 동적 제거 — 제약명이 환경별로 다를 수 있어 conkey로 조회.
    op.execute(
        """
        DO $$
        DECLARE
            fk_name text;
        BEGIN
            SELECT con.conname INTO fk_name
            FROM pg_constraint con
            JOIN pg_class rel       ON rel.oid = con.conrelid
            JOIN pg_attribute att   ON att.attrelid = con.conrelid
                                   AND att.attnum = ANY (con.conkey)
            WHERE rel.relname = 'routine_exercises'
              AND con.contype = 'f'
              AND att.attname = 'equipment_id'
            LIMIT 1;
            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE routine_exercises DROP CONSTRAINT %I', fk_name);
            END IF;
        END $$;
        """
    )

    # RESTRICT FK 재생성 (NOT VALID → VALIDATE: 테이블 풀스캔 락 최소화)
    op.execute(
        """
        ALTER TABLE routine_exercises
        ADD CONSTRAINT routine_exercises_equipment_id_fkey
        FOREIGN KEY (equipment_id) REFERENCES equipments (id)
        ON DELETE RESTRICT
        NOT VALID
        """
    )
    op.execute("ALTER TABLE routine_exercises VALIDATE CONSTRAINT routine_exercises_equipment_id_fkey")

    # 컬럼 NOT NULL 승격
    op.execute("ALTER TABLE routine_exercises ALTER COLUMN equipment_id SET NOT NULL")


def downgrade() -> None:
    # 제약만 원복(비파괴). 백필된 equipment_id 값은 유지한다.
    op.execute("ALTER TABLE routine_exercises ALTER COLUMN equipment_id DROP NOT NULL")
    op.execute(
        """
        DO $$
        DECLARE
            fk_name text;
        BEGIN
            SELECT con.conname INTO fk_name
            FROM pg_constraint con
            JOIN pg_class rel       ON rel.oid = con.conrelid
            JOIN pg_attribute att   ON att.attrelid = con.conrelid
                                   AND att.attnum = ANY (con.conkey)
            WHERE rel.relname = 'routine_exercises'
              AND con.contype = 'f'
              AND att.attname = 'equipment_id'
            LIMIT 1;
            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE routine_exercises DROP CONSTRAINT %I', fk_name);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        ALTER TABLE routine_exercises
        ADD CONSTRAINT routine_exercises_equipment_id_fkey
        FOREIGN KEY (equipment_id) REFERENCES equipments (id)
        ON DELETE SET NULL
        """
    )
