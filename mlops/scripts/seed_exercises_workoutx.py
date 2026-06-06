"""WorkoutX 운동 재시드 정본 — exercises + exercise_muscles 적재.

clean_slate_reseed 마이그레이션이 비운 exercises / exercise_muscles 를 채운다.
seed_reference_data.py(muscle_groups / equipments / ...) 를 **먼저** 실행해야 한다
(exercise_muscles 가 muscle_groups canon-20 에 의존).

실행:
    cd /path/to/scifit-sync
    # 1) 레퍼런스 먼저
    python mlops/scripts/seed_reference_data.py
    # 2) 운동 (이 스크립트)
    python mlops/scripts/seed_exercises_workoutx.py

소스:
    docs/handoff/workoutx-raw/exercises.json (frozen 1324운동).
    라이브 API 재호출은 변동 차단을 위해 기본 사용하지 않는다. WORKOUTX_LIVE=1 일 때만
    실 API 페이지네이션 fetch (테스트/재수집용).

WorkoutX 재설계 Phase 1 정본 (codex 3-pass 반영):
    1) name_en dedup (keep-last) — exercises.json 의 6건 중복이 on_conflict_do_update 배치에서
       CardinalityViolation 을 일으키므로 사전 제거.
    2) category = bodyPart 원문 보존 (6부위 매핑 폐기 — WORKOUTX_TARGET_TO_CATEGORY 제거).
    3) load_mode = WorkoutX equipment → 11종 canonical 매핑 (_WX_LOAD_MODE). 미지원값은
       skip 이 아닌 **fail-fast** (NULL load_mode garbage 방지).
    4) exercise_equipment junction 은 **채우지 않는다** — Phase 7 Gemini 검증 산출물 전용
       (broad/첫후보 자동생성 시 over-linking 재발).
    5) exercise_muscles: target → primary, secondaryMuscles → _SECONDARY_TO_CANON 정규화 →
       secondary. activation_pct 는 병합맵(있으면) 또는 NULL (seed_activation_pct.py 가 후속 백필).

멱등성: 모든 INSERT 는 on_conflict_do_update / on_conflict_do_nothing.
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / "mlops" / ".env")
load_dotenv(REPO_ROOT / "server" / ".env", override=True)

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 경로/소스 상수
# ---------------------------------------------------------------------------
_WORKOUTX_RAW = REPO_ROOT / "docs" / "handoff" / "workoutx-raw"
_EXERCISES_JSON = _WORKOUTX_RAW / "exercises.json"

_BASE_URL = "https://api.workoutxapp.com/v1"
_PAGE_SIZE = 100

# ---------------------------------------------------------------------------
# load_mode 매핑 — WorkoutX equipment 문자열(lower) → 11종 canonical load_mode.
# SOT: server/app/api/v1/admin.py:_WX_LOAD_MODE + docs/handoff/workoutx-raw/freeweight_load_modes.csv
#      + server/app/services/load_calc.py(FREEWEIGHT_MODES/MACHINE_MODES/cardio).
#
# canonical 11종: barbell / ez_barbell / trap_bar / dumbbell / bodyweight / weighted /
#                 kettlebell / band / cable / machine / cardio
#
# frozen exercises.json(1324) 의 34종 distinct equipment 문자열을 **전수** 매핑한다.
# 미지원값은 skip(→ NULL garbage) 이 아닌 fail-fast(KeyError) — 데이터 진화로 신규 문자열이
# 들어오면 즉시 발견되도록 한다. ez barbell→ez_barbell, trap bar→trap_bar 는 barbell 붕괴 금지.
# ---------------------------------------------------------------------------
_WX_LOAD_MODE: dict[str, str] = {
    # ── barbell 계열 (D8: ez/trap 별도) ──────────────────────────────────
    "barbell": "barbell",
    "olympic barbell": "barbell",
    "ez barbell": "ez_barbell",
    "ez barbell, exercise ball": "ez_barbell",
    "trap bar": "trap_bar",
    # ── dumbbell 계열 (보조 도구 부착 변형 포함) ─────────────────────────
    "dumbbell": "dumbbell",
    "dumbbell (used as handles for deeper range)": "dumbbell",
    "dumbbell, exercise ball": "dumbbell",
    "dumbbell, exercise ball, tennis ball": "dumbbell",
    # ── bodyweight 계열 (자체 부하 + 안정구/롤러 등 기구 없는 변형) ──────
    "body weight": "bodyweight",
    "body weight (with resistance band)": "bodyweight",
    "stability ball": "bodyweight",
    "bosu ball": "bodyweight",
    "roller": "bodyweight",
    "wheel roller": "bodyweight",
    "medicine ball": "bodyweight",
    "rope": "bodyweight",
    # ── weighted (체중 + 외부 부하, D13: bodyweight 와 분리) ──────────────
    "weighted": "weighted",
    # ── kettlebell ───────────────────────────────────────────────────────
    "kettlebell": "kettlebell",
    # ── band (탄성 부하) ─────────────────────────────────────────────────
    "band": "band",
    "resistance band": "band",
    # ── cable ────────────────────────────────────────────────────────────
    "cable": "cable",
    # ── machine 계열 (레버리지/스미스/어시스티드/슬레드/해머/타이어) ─────
    "leverage machine": "machine",
    "smith machine": "machine",
    "assisted": "machine",
    "assisted (towel)": "machine",
    "sled machine": "machine",
    "hammer": "machine",
    "tire": "machine",
    # ── cardio (부하 개념 없음, load_calc 0.0) ───────────────────────────
    "stationary bike": "cardio",
    "upper body ergometer": "cardio",
    "elliptical machine": "cardio",
    "skierg machine": "cardio",
    "stepmill machine": "cardio",
}


def resolve_load_mode(wx_equipment: str) -> str:
    """WorkoutX equipment 문자열 → canonical load_mode. 미지원값은 fail-fast(ValueError)."""
    key = (wx_equipment or "").strip().lower()
    try:
        return _WX_LOAD_MODE[key]
    except KeyError as e:
        raise ValueError(
            f"매핑되지 않은 WorkoutX equipment: {wx_equipment!r} (lower={key!r}). "
            "_WX_LOAD_MODE 에 추가하거나 데이터를 확인하세요 (fail-fast)."
        ) from e


# ---------------------------------------------------------------------------
# secondaryMuscles → canon-20 정규화 맵.
# SOT: docs/handoff/workoutx-raw/muscle_normalization.md L20-54 (35행 전체 전사, identity 포함).
# DROP 5종(Ankles/Feet/Ankle Stabilizers/Hands/Shins)은 본 맵에서 제외 → secondary 미생성.
# 한 운동에서 정규화 후 primary(target)와 같은 canon 이면 primary 우선(secondary 무시).
# ---------------------------------------------------------------------------
_SECONDARY_TO_CANON: dict[str, str] = {
    "Shoulders": "Delts",
    "Hamstrings": "Hamstrings",
    "Forearms": "Forearms",
    "Triceps": "Triceps",
    "Biceps": "Biceps",
    "Quadriceps": "Quads",
    "Calves": "Calves",
    "Glutes": "Glutes",
    "Core": "Abs",
    "Chest": "Pectorals",
    "Hip Flexors": "Hip Flexors",
    "Obliques": "Abs",
    "Lower Back": "Spine",
    "Rhomboids": "Upper Back",
    "Trapezius": "Traps",
    "Upper Back": "Upper Back",
    "Traps": "Traps",
    "Deltoids": "Delts",
    "Rear Deltoids": "Delts",
    "Brachialis": "Biceps",
    "Back": "Spine",
    "Rotator Cuff": "Delts",
    "Latissimus Dorsi": "Lats",
    "Soleus": "Calves",
    "Upper Chest": "Pectorals",
    "Wrists": "Forearms",
    "Wrist Extensors": "Forearms",
    "Wrist Flexors": "Forearms",
    "Sternocleidomastoid": "Levator Scapulae",
    "Abdominals": "Abs",
    "Grip Muscles": "Forearms",
    "Lower Abs": "Abs",
    "Inner Thighs": "Adductors",
    "Groin": "Adductors",
    "Lats": "Lats",
}

# 근육 아님/잡값 — secondary 에서 제외(정규화 맵에 없으면 자연히 skip 되나 명시 보존).
_SECONDARY_DROP: frozenset[str] = frozenset({"Ankles", "Feet", "Ankle Stabilizers", "Hands", "Shins"})

# canon-20 muscle_groups (seed_reference_data._MUSCLE_GROUPS 와 일치 — assert 기준).
_CANON_MUSCLE_NAMES: frozenset[str] = frozenset(
    {
        "Abs",
        "Pectorals",
        "Biceps",
        "Glutes",
        "Delts",
        "Triceps",
        "Upper Back",
        "Lats",
        "Calves",
        "Quads",
        "Forearms",
        "Cardiovascular System",
        "Hamstrings",
        "Spine",
        "Traps",
        "Adductors",
        "Serratus Anterior",
        "Abductors",
        "Levator Scapulae",
        "Hip Flexors",
    }
)


def normalize_secondary(raw: str) -> str | None:
    """secondaryMuscles 원소 → canon-20 또는 None(drop/미매핑).

    DROP 5종 및 정규화 맵에 없는 값은 None (secondary 미생성).
    """
    name = (raw or "").strip()
    if not name or name in _SECONDARY_DROP:
        return None
    return _SECONDARY_TO_CANON.get(name)


# ---------------------------------------------------------------------------
# activation_pct 병합맵 (optional).
#   기본은 빈 맵 → 모든 activation_pct = NULL. seed_activation_pct.py 가 Gemini 로 후속 백필.
#   파일이 존재하면 로드: (exercise_name_en, canon_muscle_name) → int 0~100.
#   CSV 포맷: exercise_name_en,muscle_name,activation_pct
# ---------------------------------------------------------------------------
_ACTIVATION_CSV = _WORKOUTX_RAW / "muscle_activation_seed.csv"


def load_activation_merge_map() -> dict[tuple[str, str], int]:
    """activation_pct 병합맵 로드. 파일 없으면 빈 맵(전부 NULL)."""
    merge: dict[tuple[str, str], int] = {}
    if not _ACTIVATION_CSV.exists():
        logger.info("activation 병합맵 없음(%s) — activation_pct 전부 NULL, 후속 백필 대상", _ACTIVATION_CSV.name)
        return merge

    import csv

    with open(_ACTIVATION_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            ex = (r.get("exercise_name_en") or "").strip()
            mus = (r.get("muscle_name") or "").strip()
            pct_raw = (r.get("activation_pct") or "").strip()
            if not ex or not mus or not pct_raw:
                continue
            try:
                pct = int(float(pct_raw))
            except ValueError:
                continue
            if 0 <= pct <= 100:
                merge[(ex, mus)] = pct
    logger.info("activation 병합맵 로드: %d건", len(merge))
    return merge


# ---------------------------------------------------------------------------
# 소스 로더
# ---------------------------------------------------------------------------


def load_exercises_from_frozen() -> list[dict]:
    """frozen exercises.json(1324) 로드 — 라이브 변동 차단 기본 소스."""
    with open(_EXERCISES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "data" in data:
        items = data["data"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"예상치 못한 exercises.json 구조: {type(data).__name__}")
    logger.info("frozen exercises.json 로드: %d운동", len(items))
    return items


async def fetch_all_exercises_live(api_key: str) -> list[dict]:
    """WorkoutX 실 API 페이지네이션 fetch (WORKOUTX_LIVE=1 일 때만 — 재수집용)."""
    import httpx

    exercises: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(
        base_url=_BASE_URL,
        headers={"X-WorkoutX-Key": api_key},
        timeout=30.0,
    ) as client:
        while True:
            resp = await client.get("/exercises", params={"limit": _PAGE_SIZE, "offset": offset})
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict) and "data" in data:
                batch = data["data"]
                total = data.get("total", 0)
            elif isinstance(data, list):
                batch = data
                total = len(batch)
            else:
                break

            exercises.extend(batch)
            offset += len(batch)
            logger.info("WorkoutX 운동 가져옴: %d / %d", offset, total)

            if not batch or offset >= total:
                break

    return exercises


def dedup_by_name_en(exercises: list[dict]) -> list[dict]:
    """name_en(=name) 기준 dedup, keep-last.

    exercises.json 의 6건 중복(Barbell Seated Calf Raise 등)이 on_conflict_do_update 단일
    배치에서 CardinalityViolation(ON CONFLICT DO UPDATE 가 같은 행을 두 번 건드림)을 유발하므로
    배치 적재 전에 반드시 제거한다. keep-last: 뒤 항목으로 덮어쓴다(dict 삽입 순서 보존).
    """
    by_name: dict[str, dict] = {}
    for ex in exercises:
        name_en = (ex.get("name") or "").strip()
        if not name_en:
            continue
        by_name[name_en] = ex  # keep-last
    deduped = list(by_name.values())
    removed = len({(e.get("name") or "").strip() for e in exercises if (e.get("name") or "").strip()})
    if removed != len(deduped):  # 방어 — 정상이면 동일
        logger.warning("dedup 카운트 불일치: unique=%d, deduped=%d", removed, len(deduped))
    dropped = len([e for e in exercises if (e.get("name") or "").strip()]) - len(deduped)
    logger.info("name_en dedup: 입력 %d → %d (중복 %d건 제거, keep-last)", len(exercises), len(deduped), dropped)
    return deduped


# ---------------------------------------------------------------------------
# DB 적재
# ---------------------------------------------------------------------------


async def assert_muscle_groups_canon(session: AsyncSession) -> dict[str, uuid.UUID]:
    """canon-20 muscle_groups 가 모두 존재하는지 assert 하고 name→id 룩업을 반환한다.

    seed_reference_data.py 선행 실행 가정. 누락 시 RuntimeError(fail-fast).
    """
    result = await session.execute(text("SELECT name, id FROM muscle_groups"))
    mg_by_name = {row.name: row.id for row in result}
    missing = _CANON_MUSCLE_NAMES - set(mg_by_name.keys())
    if missing:
        raise RuntimeError(
            f"muscle_groups canon-20 assert 실패 — 누락: {sorted(missing)}. seed_reference_data.py 를 먼저 실행하세요."
        )
    logger.info("muscle_groups canon-20 assert OK (DB=%d종)", len(mg_by_name))
    return mg_by_name


async def upsert_exercises(session: AsyncSession, exercises: list[dict]) -> int:
    """exercises 테이블 upsert. category=bodyPart 원문, load_mode 채움. 처리 건수 반환.

    bodyPart 빈값 → category NOT NULL 위반 방어로 skip(경고).
    load_mode 는 fail-fast(미지원 equipment → ValueError 전파).
    """
    from app.models.exercise import Exercise  # noqa: E402

    rows = []
    skipped = 0
    for ex in exercises:
        name_en = (ex.get("name") or "").strip()
        if not name_en:
            continue

        body_part = (ex.get("bodyPart") or "").strip()
        if not body_part:
            logger.warning("운동 '%s' bodyPart 없음, skip (category NOT NULL)", name_en)
            skipped += 1
            continue

        load_mode = resolve_load_mode(ex.get("equipment", ""))  # fail-fast

        rows.append(
            {
                "name": name_en,
                "name_en": name_en,
                "category": body_part,  # SOT: bodyPart 원문 (6부위 매핑 폐기)
                "gif_url": ex.get("gifUrl"),
                "load_mode": load_mode,
            }
        )

    if skipped:
        logger.warning("exercises: bodyPart 없음으로 %d건 skip", skipped)
    if not rows:
        return 0

    stmt = pg_insert(Exercise).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["name_en"],
        set_={
            "name": stmt.excluded.name,
            "category": stmt.excluded.category,
            "gif_url": stmt.excluded.gif_url,
            "load_mode": stmt.excluded.load_mode,
        },
    )
    await session.execute(stmt)
    logger.info("exercises upsert 완료: %d건", len(rows))
    return len(rows)


async def upsert_exercise_muscles(
    session: AsyncSession,
    exercises: list[dict],
    mg_by_name: dict[str, uuid.UUID],
    activation_merge: dict[tuple[str, str], int],
) -> int:
    """exercise_muscles 시드. 처리 건수 반환.

    - primary  = target (1:1, 무번역). target 이 canon-20 에 없으면 경고 후 skip.
    - secondary = secondaryMuscles → _SECONDARY_TO_CANON 정규화. drop/미매핑은 제외.
    - primary 와 같은 canon 인 secondary 는 무시(primary 우선).
    - activation_pct = activation_merge[(name_en, canon_muscle)] 또는 NULL.

    (exercise_id, muscle_group_id) PK 충돌은 on_conflict_do_update.
    """
    from app.models.exercise import Exercise, ExerciseMuscle  # noqa: E402

    # name_en → exercise_id 룩업 (upsert_exercises 커밋/flush 후 호출 가정)
    id_rows = (await session.execute(select(Exercise.id, Exercise.name_en))).all()
    name_to_id = {name_en: eid for eid, name_en in id_rows}
    # muscle_group_id → name 역룩업 (activation 병합맵 키 구성용, O(1))
    id_to_muscle = {mg_id: name for name, mg_id in mg_by_name.items()}

    rows: list[dict] = []
    missing_target = 0
    for ex in exercises:
        name_en = (ex.get("name") or "").strip()
        if not name_en:
            continue
        exercise_id = name_to_id.get(name_en)
        if exercise_id is None:
            continue  # upsert_exercises 에서 skip 된 운동(bodyPart 없음 등)

        # 한 운동 안에서 muscle_group 중복 방지 (primary 우선)
        per_ex: dict[uuid.UUID, str] = {}  # muscle_group_id → involvement

        # 1) primary = target
        target = (ex.get("target") or "").strip()
        primary_id = mg_by_name.get(target)
        if primary_id is None:
            logger.warning("운동 '%s' target '%s' 가 canon-20 에 없음, primary skip", name_en, target)
            missing_target += 1
        else:
            per_ex[primary_id] = "primary"

        # 2) secondary = secondaryMuscles 정규화
        for raw in ex.get("secondaryMuscles") or []:
            canon = normalize_secondary(raw)
            if canon is None:
                continue
            sec_id = mg_by_name.get(canon)
            if sec_id is None:
                # 정규화 맵이 canon-20 외 값을 내놓는 일은 없어야 함(방어)
                logger.warning("운동 '%s' secondary 정규화값 '%s' 가 canon-20 에 없음, skip", name_en, canon)
                continue
            if sec_id in per_ex:
                continue  # 이미 primary(또는 다른 secondary) → primary 우선 유지
            per_ex[sec_id] = "secondary"

        for mg_id, involvement in per_ex.items():
            mus_name = id_to_muscle.get(mg_id)
            pct = activation_merge.get((name_en, mus_name)) if mus_name else None
            rows.append(
                {
                    "exercise_id": exercise_id,
                    "muscle_group_id": mg_id,
                    "involvement": involvement,
                    "activation_pct": pct,
                }
            )

    if missing_target:
        logger.warning("exercise_muscles: target canon 누락으로 %d개 운동 primary skip", missing_target)
    if not rows:
        return 0

    # 배치 upsert (단일 실행에 per-(exercise,muscle) 중복이 없도록 위에서 per_ex 로 보장)
    stmt = pg_insert(ExerciseMuscle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["exercise_id", "muscle_group_id"],
        set_={
            "involvement": stmt.excluded.involvement,
            "activation_pct": stmt.excluded.activation_pct,
        },
    )
    await session.execute(stmt)
    logger.info("exercise_muscles upsert 완료: %d건", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL 환경변수 없음. server/.env 확인")
        sys.exit(1)

    # 소스 선택: 기본 frozen, WORKOUTX_LIVE=1 이면 실 API.
    if os.getenv("WORKOUTX_LIVE") == "1":
        api_key = os.getenv("WORKOUTX_API_KEY")
        if not api_key:
            logger.error("WORKOUTX_LIVE=1 이지만 WORKOUTX_API_KEY 없음")
            sys.exit(1)
        logger.info("WORKOUTX_LIVE=1 — 실 API 에서 운동 목록 수집")
        exercises_raw = await fetch_all_exercises_live(api_key)
    else:
        exercises_raw = load_exercises_from_frozen()

    # CRITICAL: name_en dedup (keep-last) — 배치 CardinalityViolation 방지
    exercises = dedup_by_name_en(exercises_raw)

    activation_merge = load_activation_merge_map()

    # asyncpg PgBouncer 호환 (statement_cache_size=0)
    connect_args: dict = {}
    if "asyncpg" in database_url:
        connect_args["statement_cache_size"] = 0

    engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session, session.begin():
        # 0) muscle_groups canon-20 선행 assert (exercise_muscles 의존)
        mg_by_name = await assert_muscle_groups_canon(session)

        # 1) exercises (category=bodyPart, load_mode)
        ex_count = await upsert_exercises(session, exercises)
        await session.flush()  # exercise_muscles 룩업이 참조할 수 있도록 flush

        # 2) exercise_muscles (target→primary, secondary→정규화, activation_pct)
        em_count = await upsert_exercise_muscles(session, exercises, mg_by_name, activation_merge)

        # exercise_equipment junction 은 채우지 않는다 (Phase 7 Gemini 검증 전용).

    await engine.dispose()

    logger.info(
        "재시드 완료 — exercises=%d, exercise_muscles=%d (exercise_equipment=0: Phase7 전용)",
        ex_count,
        em_count,
    )
    logger.info("다음 단계: python mlops/scripts/seed_activation_pct.py (activation_pct 백필)")


if __name__ == "__main__":
    asyncio.run(main())
