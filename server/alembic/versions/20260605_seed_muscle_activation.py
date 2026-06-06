"""exercise_muscles 시드 + Gemini activation% — 1355 운동(72 큐레이션 + 1283 WorkoutX)

Revision ID: 20260605_seed_activation
Revises: 20260605_normalize_muscles
Create Date: 2026-06-05

배경:
  진짜 prod(hnwegx) 운동 1401개 중 근육 매핑 보유는 70개뿐(나머지 미매핑). 매핑된 70개도
  근육 세트가 불완전(예: Back Squat 이 2근육만). 팀이 확정한 매핑:
    - 72 큐레이션(팀 수동검증, docs/handoff/2026-06-05-curated-72-final-mapping.csv)
    - 1283 WorkoutX 자동(docs/handoff/2026-06-05-workoutx-1283-mapping.csv)
  활성도%(EMG)는 WorkoutX/큐레이션에 없어 Gemini 2.5 Flash 로 일괄 추정(generated seed CSV).
  선행 normalize_muscles 가 muscle_groups 를 슬러그 표준으로 정규화 → 본 마이그의 슬러그 JOIN 성립.

시드 데이터: server/alembic/data/muscle_activation_seed.csv
  (exercise_name, muscle_slug, role, activation_pct) — 결정값. 마이그가 읽어 멱등 적용.

동작:
  CSV 의 1355 운동 각각: 기존 exercise_muscles DELETE → CSV 행 INSERT (name_en + muscle slug JOIN).
  - DELETE+replace 는 #284 와 동일한 결정론 패턴. 큐레이션 50개의 기존 부분매핑을 팀확정본으로 교체.
  - CSV 밖 운동(예: 'Deadlift','Squat' 등 기존 매핑 17개)은 DELETE 대상 아님 → 보존.
  - exercise 가 없는 환경(clean CI DB 는 1283 WorkoutX 운동 미보유 — admin API 적재라 Alembic 밖)은
    INSERT...SELECT 가 0행 → 자동 skip. prod(hnwegx)는 1355 전부 존재 → 전량 적용.

★ muscle_group_id 하드코딩 금지 — muscle slug(=정규화된 name)로 JOIN. exercise 도 name_en 으로 JOIN.
asyncpg 안전: 단건 named param 루프(ANY(:list) 회피, recover_default_equip 패턴).
안전: exercise_muscles 는 순수 참조 데이터 → 사용자 루틴/기록 무관(DELETE 해도 손실 0).
멱등: DELETE→INSERT(ON CONFLICT DO UPDATE) 반복 시 동일 최종 상태.
downgrade no-op: 이전 부분매핑 복원 무의미.
"""

import csv
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "20260605_seed_activation"
down_revision = "20260605_normalize_muscles"
branch_labels = None
depends_on = None

_SEED_CSV = Path(__file__).resolve().parent.parent / "data" / "muscle_activation_seed.csv"


def _load_seed() -> list[dict]:
    if not _SEED_CSV.exists():
        raise RuntimeError(f"시드 CSV 없음: {_SEED_CSV}")
    with _SEED_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError(f"시드 CSV 비어있음: {_SEED_CSV}")
    return rows


def upgrade() -> None:
    conn = op.get_bind()
    rows = _load_seed()

    # 1) CSV 운동별 기존 exercise_muscles DELETE (단건 루프). name_en 은 prod/clean 모두 unique.
    exercises = sorted({r["exercise_name"].strip() for r in rows})
    for name in exercises:
        conn.execute(
            text("DELETE FROM exercise_muscles WHERE exercise_id = (SELECT id FROM exercises WHERE name_en = :nm)"),
            {"nm": name},
        )

    # 2) CSV 행 INSERT (name_en + muscle slug JOIN). 미존재 운동/슬러그는 SELECT 0행 → skip.
    inserted = 0
    for r in rows:
        name = r["exercise_name"].strip()
        slug = r["muscle_slug"].strip()
        role = r["role"].strip()
        pct = int(r["activation_pct"])
        res = conn.execute(
            text(
                """
                INSERT INTO exercise_muscles (exercise_id, muscle_group_id, involvement, activation_pct)
                SELECT e.id, m.id, :role, :pct
                FROM exercises e
                JOIN muscle_groups m ON m.name = :slug
                WHERE e.name_en = :nm
                ON CONFLICT (exercise_id, muscle_group_id)
                DO UPDATE SET involvement = EXCLUDED.involvement, activation_pct = EXCLUDED.activation_pct
                """
            ),
            {"role": role, "pct": pct, "slug": slug, "nm": name},
        )
        inserted += res.rowcount or 0

    # 3) 가드: 슬러그 미해석(정규화 누락)은 치명적 → 검출. exercise 미존재(clean DB)는 정상 skip.
    seed_slugs = {r["muscle_slug"].strip() for r in rows}
    missing_slugs = [
        s
        for s in sorted(seed_slugs)
        if conn.execute(text("SELECT 1 FROM muscle_groups WHERE name = :s"), {"s": s}).first() is None
    ]
    if missing_slugs:
        raise RuntimeError(f"muscle slug 미해석 {len(missing_slugs)}종 — normalize_muscles 선행 누락? {missing_slugs}")


def downgrade() -> None:
    # no-op: 이전 부분매핑 복원 무의미. exercise_muscles 정리는 상위 시드/정규화 정책이 담당.
    pass
