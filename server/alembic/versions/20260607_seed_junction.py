"""exercise_equipment junction 시드 — machine/cable 운동 ↔ 실물 기구 (D12/D14).

Revision ID: 20260607_seed_junction
Revises: 20260607_salvage_activation
Create Date: 2026-06-07

배경:
  reseed_workoutx 는 exercise_equipment junction 을 비워둔다(D12: Gemini 검증 후 적재).
  본 마이그가 machine/cable load_mode 운동을 실물 기구에 매핑해 채운다.
  근육 활성도는 운동 기준(exercise_muscles)이라 junction 과 무관 — junction 은 오직
  "가용성(D14: 이 gym 에서 이 운동 가능?) + 중량계산(기구 pulley/bar)" 만 담당한다.

데이터: server/alembic/data/junction_seed.csv (mlops/scripts/gen_junction_seed.py 산출).
  컬럼 = exercise_name, equipment_id, source, confidence.
  - source='seed'   : 결정론(smith machine→Smith 직결 / cable→Cable / bodyPart→category + 동작 키워드 매칭).
  - source='gemini' : LLM 휴리스틱(calf→Leg Press·Hack / pull·chin→Assisted Dip·Lat Pulldown /
                      dip→Assisted Dip / shrug·deadlift→Smith / hip→Hip add·abd / sit-up·twist→core).
  machine/cable 316 운동 중 297(94%) 매핑. 미매핑 19 = 스트레치/유산소/맨몸(hanging)/기능성(타이어·
  해머·그립) — 머신 부하가 무의미해 junction 을 만들지 않음(G4).

적용: clean_slate→reseed_workoutx→salvage_activation→본 마이그 순으로 자동 배포.
  exercise=name_en JOIN, equipment_id 는 CSV 의 실물 UUID(reseed 가 선적재). 멱등 ON CONFLICT.

[논문 절대 불가침] papers / paper_chunks 에 대한 DELETE/DROP/ALTER 0건.
"""

import csv
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260607_seed_junction"
down_revision = "20260607_salvage_activation"
branch_labels = None
depends_on = None

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_JUNCTION_CSV = _DATA_DIR / "junction_seed.csv"


def _rows() -> list[dict]:
    with open(_JUNCTION_CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def upgrade() -> None:
    conn = op.get_bind()
    rows = _rows()
    inserted = 0
    for r in rows:
        name = (r.get("exercise_name") or "").strip()
        eq_id = (r.get("equipment_id") or "").strip()
        source = (r.get("source") or "seed").strip() or "seed"
        conf_raw = (r.get("confidence") or "").strip()
        if not name or not eq_id:
            continue
        try:
            conf = float(conf_raw) if conf_raw else None
        except ValueError:
            conf = None
        res = conn.execute(
            sa.text(
                """
                INSERT INTO exercise_equipment (exercise_id, equipment_id, source, confidence)
                SELECT e.id, :eq_id, :source, :conf
                FROM   exercises e
                WHERE  e.name_en = :name
                ON CONFLICT (exercise_id, equipment_id) DO UPDATE
                    SET source     = EXCLUDED.source,
                        confidence = EXCLUDED.confidence
                """
            ),
            {"eq_id": eq_id, "source": source, "conf": conf, "name": name},
        )
        inserted += res.rowcount or 0
    import logging

    logging.getLogger("alembic").info("junction 시드: exercise_equipment %d행 upsert (CSV %d행).", inserted, len(rows))


def downgrade() -> None:
    """junction 시드 역연산 — 본 마이그가 적재한 (exercise, equipment) 쌍 삭제."""
    conn = op.get_bind()
    for r in _rows():
        name = (r.get("exercise_name") or "").strip()
        eq_id = (r.get("equipment_id") or "").strip()
        if not name or not eq_id:
            continue
        conn.execute(
            sa.text(
                """
                DELETE FROM exercise_equipment
                WHERE equipment_id = :eq_id
                  AND exercise_id = (SELECT id FROM exercises WHERE name_en = :name)
                """
            ),
            {"eq_id": eq_id, "name": name},
        )
