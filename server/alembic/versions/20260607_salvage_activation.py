"""activation_pct salvage — 해부학 muscle_activation_seed → WorkoutX canon-20 백필 (D9).

Revision ID: 20260607_salvage_activation
Revises: 20260606_reseed_workoutx
Create Date: 2026-06-07

배경:
  reseed_workoutx 는 exercise_muscles 의 involvement(WorkoutX target/secondary)만 채우고
  activation_pct 는 전부 NULL 로 둔다(D9). 본 마이그가 검증된 해부학 활성도 수치
  (server/alembic/data/muscle_activation_seed.csv, 3893행)를 canon-20 으로 변환해 salvage 한다.

D9: activation% = muscle_activation_seed(해부학 slug) → 병합 맵(MAX) salvage, 매칭 없으면 NULL.
  - slug → canon-20 muscle_groups.name 매핑(_SLUG_TO_CANON, 사용자 검증 2026-06-07:
    trapezius→Traps / gluteus_medius→Abductors / rotator_cuff→Delts / pectoralis_minor→Pectorals).
  - exercise = name_en JOIN, muscle = canon name JOIN.
  - 같은 (exercise, canon)에 여러 slug 가 매핑되면 activation_pct = MAX (primary 우선과 일치 —
    primary 근육이 통상 더 높은 활성도). involvement 는 reseed(WorkoutX 권위) 유지 — 본 마이그는
    activation_pct 만 UPDATE 한다.
  - reseed 가 만든 exercise_muscles 행에만 적용(UPDATE). seed 에만 있는 (exercise, canon)
    조합은 0행(버려짐), reseed 에만 있는 행은 NULL 유지(추후 보강 대상).

배포: clean_slate→reseed_workoutx→본 마이그 순으로 deploy.yml `alembic upgrade head` 에서 자동 적용
  (server/alembic/data CSV 는 Dockerfile `COPY server/ /app/` 에 자동 포함).

멱등: 동일 CSV → 동일 최종 activation_pct.
[논문 절대 불가침] papers / paper_chunks 에 대한 DELETE/DROP/ALTER 0건.
"""

import csv
import logging
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260607_salvage_activation"
down_revision = "20260606_reseed_workoutx"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_ACTIVATION_CSV = _DATA_DIR / "muscle_activation_seed.csv"

# ---------------------------------------------------------------------------
# 해부학 muscle_slug → canon-20 muscle_groups.name 매핑.
#   muscle_activation_seed.csv 에 등장하는 distinct slug 27종 기준(사용자 검증 2026-06-07).
#   canon-20 = reseed_workoutx._MUSCLE_GROUPS (Title-Case).
#   매핑에 없는 slug(잡값 " Arms Straight)" 등)는 skip → 해당 행 미반영.
# ---------------------------------------------------------------------------
_SLUG_TO_CANON: dict[str, str] = {
    "triceps_brachii": "Triceps",
    "biceps_brachii": "Biceps",
    "brachialis": "Biceps",
    "forearms": "Forearms",
    "hamstrings": "Hamstrings",
    "gluteus_maximus": "Glutes",
    "gluteus_medius": "Abductors",
    "adductors": "Adductors",
    "anterior_deltoid": "Delts",
    "lateral_deltoid": "Delts",
    "posterior_deltoid": "Delts",
    "rotator_cuff": "Delts",
    "rectus_abdominis": "Abs",
    "obliques": "Abs",
    "transverse_abdominis": "Abs",
    "pectoralis_major": "Pectorals",
    "pectoralis_minor": "Pectorals",
    "serratus_anterior": "Serratus Anterior",
    "trapezius": "Traps",
    "rhomboids": "Upper Back",
    "latissimus_dorsi": "Lats",
    "erector_spinae": "Spine",
    "levator_scapulae": "Levator Scapulae",
    "calves": "Calves",
    "quadriceps": "Quads",
    "hip_flexors": "Hip Flexors",
}


def upgrade() -> None:
    conn = op.get_bind()

    # 0) activation_source 컬럼 추가(멱등) — 검증값(anatomy_seed)/추정값(gemini) 구분 메타.
    op.execute("ALTER TABLE exercise_muscles ADD COLUMN IF NOT EXISTS activation_source varchar(20)")

    # 1) CSV → (exercise_name, canon) 별 MAX(activation_pct) 집계.
    agg: dict[tuple[str, str], int] = {}
    skipped_slugs: set[str] = set()
    with open(_ACTIVATION_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            slug = (r.get("muscle_slug") or "").strip()
            canon = _SLUG_TO_CANON.get(slug)
            if canon is None:
                if slug:
                    skipped_slugs.add(slug)
                continue
            name = (r.get("exercise_name") or "").strip()
            raw = (r.get("activation_pct") or "").strip()
            if not name or not raw:
                continue
            try:
                pct = int(float(raw))
            except ValueError:
                continue
            key = (name, canon)
            if pct > agg.get(key, -1):
                agg[key] = pct

    if skipped_slugs:
        logger.info(
            "activation salvage: 매핑 없는 slug %d종 skip(잡값/미지원): %s",
            len(skipped_slugs),
            sorted(skipped_slugs),
        )

    # 2) reseed 가 만든 exercise_muscles 행에만 activation_pct UPDATE (involvement 불변).
    #    name_en + canon name JOIN. 미존재 조합은 rowcount 0 → 자연 skip.
    updated = 0
    for (name, canon), pct in agg.items():
        res = conn.execute(
            sa.text(
                """
                UPDATE exercise_muscles em
                SET activation_pct = :pct,
                    activation_source = 'anatomy_seed'
                FROM exercises e, muscle_groups m
                WHERE em.exercise_id = e.id
                  AND em.muscle_group_id = m.id
                  AND e.name_en = :name
                  AND m.name = :canon
                """
            ),
            {"pct": pct, "name": name, "canon": canon},
        )
        updated += res.rowcount or 0

    logger.info(
        "activation salvage: exercise_muscles %d행 activation_pct 채움 (집계 %d (운동,근육) 조합).",
        updated,
        len(agg),
    )


def downgrade() -> None:
    """salvage 역연산 — reseed 직후 상태(activation_pct 전량 NULL)로 복원.

    본 마이그 적용 전 activation_pct 는 reseed_workoutx 가 전부 NULL 로 둔 상태이므로,
    전량 NULL 로 되돌리는 것이 정확한 역연산이다(involvement 는 미접촉).
    """
    op.execute("UPDATE exercise_muscles SET activation_pct = NULL, activation_source = NULL")
