"""재시드 정본 — muscle_groups / equipment_brands / equipments / gym_equipments 적재.

clean_slate_reseed 마이그레이션이 빈 상태로 만든 레퍼런스 테이블을 채운다.
seed_exercises_workoutx.py 보다 먼저 실행해야 한다 (exercises/exercise_muscles 선행 의존 없음).

실행:
    cd /path/to/scifit-sync
    python mlops/scripts/seed_reference_data.py

환경변수:
    DATABASE_URL  — server/.env 에서 로드 (asyncpg 드라이버 필수)

멱등성: 모든 INSERT 는 on_conflict_do_update 또는 on_conflict_do_nothing.
"""

import asyncio
import csv
import json
import logging
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / "mlops" / ".env")
load_dotenv(REPO_ROOT / "server" / ".env", override=True)

import os  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 경로 상수
# ---------------------------------------------------------------------------
_DB_EXPORT = REPO_ROOT / "docs" / "handoff" / "db-export"
_BRANDS_CSV = _DB_EXPORT / "equipment_brands.csv"
_EQUIPMENTS_CSV = _DB_EXPORT / "equipments.csv"
_GYM_EQUIPMENTS_CSV = _DB_EXPORT / "gym_equipments.csv"

# ---------------------------------------------------------------------------
# muscle_groups 20 캐노니컬 (muscle_normalization.md 기준)
# name: Title-Case (WorkoutX API target 원문)
# name_ko: 해부학 한국어
# body_region: upper_body / lower_body / core / cardio
# ---------------------------------------------------------------------------
_MUSCLE_GROUPS: list[dict] = [
    {"name": "Abs", "name_ko": "복근", "body_region": "core"},
    {"name": "Pectorals", "name_ko": "대흉근", "body_region": "upper_body"},
    {"name": "Biceps", "name_ko": "이두근", "body_region": "upper_body"},
    {"name": "Glutes", "name_ko": "둔근", "body_region": "lower_body"},
    {"name": "Delts", "name_ko": "삼각근", "body_region": "upper_body"},
    {"name": "Triceps", "name_ko": "삼두근", "body_region": "upper_body"},
    {"name": "Upper Back", "name_ko": "상배근", "body_region": "upper_body"},
    {"name": "Lats", "name_ko": "광배근", "body_region": "upper_body"},
    {"name": "Calves", "name_ko": "종아리", "body_region": "lower_body"},
    {"name": "Quads", "name_ko": "대퇴사두근", "body_region": "lower_body"},
    {"name": "Forearms", "name_ko": "전완근", "body_region": "upper_body"},
    {"name": "Cardiovascular System", "name_ko": "심혈관계", "body_region": "cardio"},
    {"name": "Hamstrings", "name_ko": "햄스트링", "body_region": "lower_body"},
    {"name": "Spine", "name_ko": "척추기립근", "body_region": "upper_body"},
    {"name": "Traps", "name_ko": "승모근", "body_region": "upper_body"},
    {"name": "Adductors", "name_ko": "내전근", "body_region": "lower_body"},
    {"name": "Serratus Anterior", "name_ko": "전거근", "body_region": "upper_body"},
    {"name": "Abductors", "name_ko": "외전근", "body_region": "lower_body"},
    {"name": "Levator Scapulae", "name_ko": "견갑거근", "body_region": "upper_body"},
    {"name": "Hip Flexors", "name_ko": "고관절굴곡근", "body_region": "lower_body"},
]


def _read_csv(path: Path) -> list[dict]:
    """utf-8-sig CSV → dict 리스트."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _parse_optional_float(val: str) -> float | None:
    v = val.strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _parse_bool(val: str) -> bool:
    return val.strip().upper() in ("TRUE", "1", "YES")


def _parse_jsonb(val: str) -> dict | None:
    v = val.strip()
    if not v:
        return None
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        return None


def _parse_optional_str(val: str) -> str | None:
    v = val.strip()
    return v if v else None


# ---------------------------------------------------------------------------
# upsert helpers
# ---------------------------------------------------------------------------


async def upsert_muscle_groups(session: AsyncSession) -> int:
    """muscle_groups 20 캐노니컬 upsert. name(UNIQUE) conflict → name_ko/body_region 갱신."""
    from app.models.exercise import MuscleGroup  # noqa: E402

    rows = [
        {
            "id": uuid.uuid4(),
            "name": mg["name"],
            "name_ko": mg["name_ko"],
            "body_region": mg["body_region"],
        }
        for mg in _MUSCLE_GROUPS
    ]

    stmt = pg_insert(MuscleGroup).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={
            "name_ko": stmt.excluded.name_ko,
            "body_region": stmt.excluded.body_region,
        },
    )
    await session.execute(stmt)
    logger.info("muscle_groups upsert 완료: %d건", len(rows))
    return len(rows)


async def assert_muscle_groups_exist(session: AsyncSession) -> None:
    """seed_exercises_workoutx.py 실행 전 선행 assert — 20 캐노니컬이 모두 존재해야 함."""
    result = await session.execute(text("SELECT count(*) FROM muscle_groups"))
    cnt = result.scalar_one()
    expected = len(_MUSCLE_GROUPS)
    if cnt < expected:
        raise RuntimeError(
            f"muscle_groups assert 실패: DB={cnt} < expected={expected}. seed_reference_data.py 를 먼저 실행하세요."
        )
    logger.info("muscle_groups assert OK: %d건", cnt)


async def upsert_equipment_brands(session: AsyncSession) -> int:
    """equipment_brands.csv(14행) upsert. id 명시(UUID 고정)."""
    from app.models.gym import EquipmentBrand  # noqa: E402

    rows_raw = _read_csv(_BRANDS_CSV)
    rows = []
    for r in rows_raw:
        rows.append(
            {
                "id": uuid.UUID(r["id"]),
                "name": r["name"].strip(),
                "logo_url": _parse_optional_str(r.get("logo_url", "")),
                "default_bar_unit": r.get("default_bar_unit", "kg").strip() or "kg",
                "default_stack_unit": r.get("default_stack_unit", "kg").strip() or "kg",
            }
        )

    stmt = pg_insert(EquipmentBrand).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "name": stmt.excluded.name,
            "logo_url": stmt.excluded.logo_url,
            "default_bar_unit": stmt.excluded.default_bar_unit,
            "default_stack_unit": stmt.excluded.default_stack_unit,
        },
    )
    await session.execute(stmt)
    logger.info("equipment_brands upsert 완료: %d건", len(rows))
    return len(rows)


async def upsert_equipments(session: AsyncSession) -> int:
    """equipments.csv(132행) upsert. id 명시.

    is_freeweight 컬럼은 clean_slate_reseed Phase 2e에서 DROP됐으므로 무시.
    """
    from app.models.gym import Equipment  # noqa: E402

    rows_raw = _read_csv(_EQUIPMENTS_CSV)
    rows = []
    for r in rows_raw:
        rows.append(
            {
                "id": uuid.UUID(r["id"]),
                "brand_id": uuid.UUID(r["brand_id"]) if r.get("brand_id", "").strip() else None,
                "name": r["name"].strip(),
                "name_en": _parse_optional_str(r.get("name_en", "")),
                "category": _parse_optional_str(r.get("category", "")),
                "sub_category": _parse_optional_str(r.get("sub_category", "")),
                "equipment_type": r["equipment_type"].strip(),
                "pulley_ratio": float(r["pulley_ratio"]) if r.get("pulley_ratio", "").strip() else 1.0,
                "bar_weight": _parse_optional_float(r.get("bar_weight", "")),
                "bar_weight_unit": _parse_optional_str(r.get("bar_weight_unit", "")),
                "has_weight_assist": _parse_bool(r.get("has_weight_assist", "FALSE")),
                "min_stack": _parse_optional_float(r.get("min_stack", "")),
                "max_stack": _parse_optional_float(r.get("max_stack", "")),
                "stack_weight": _parse_jsonb(r.get("stack_weight", "")),
                "stack_unit": _parse_optional_str(r.get("stack_unit", "")),
                "image_url": _parse_optional_str(r.get("image_url", "")),
            }
        )

    stmt = pg_insert(Equipment).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "brand_id": stmt.excluded.brand_id,
            "name": stmt.excluded.name,
            "name_en": stmt.excluded.name_en,
            "category": stmt.excluded.category,
            "sub_category": stmt.excluded.sub_category,
            "equipment_type": stmt.excluded.equipment_type,
            "pulley_ratio": stmt.excluded.pulley_ratio,
            "bar_weight": stmt.excluded.bar_weight,
            "bar_weight_unit": stmt.excluded.bar_weight_unit,
            "has_weight_assist": stmt.excluded.has_weight_assist,
            "min_stack": stmt.excluded.min_stack,
            "max_stack": stmt.excluded.max_stack,
            "stack_weight": stmt.excluded.stack_weight,
            "stack_unit": stmt.excluded.stack_unit,
            "image_url": stmt.excluded.image_url,
        },
    )
    await session.execute(stmt)
    logger.info("equipments upsert 완료: %d건", len(rows))
    return len(rows)


async def upsert_gym_equipments(session: AsyncSession) -> int:
    """gym_equipments.csv(33행) upsert. (gym_id, equipment_id) PK conflict → quantity 갱신.

    참조하는 gym_id 가 gyms 테이블에 없으면 FK 위반 — gyms 는 clean_slate 에서 wipe 안 됨,
    더찬스짐(ecdd073b) 이 존재해야 한다. 존재하지 않으면 경고 후 skip.
    """
    from app.models.gym import GymEquipment  # noqa: E402

    rows_raw = _read_csv(_GYM_EQUIPMENTS_CSV)

    # gym_id 존재 확인
    gym_ids = {r["gym_id"].strip() for r in rows_raw}
    result = await session.execute(
        text("SELECT id FROM gyms WHERE id = ANY(:ids)"),
        {"ids": list(gym_ids)},
    )
    existing_gyms = {str(row[0]) for row in result}
    missing_gyms = gym_ids - existing_gyms
    if missing_gyms:
        logger.warning(
            "gym_equipments skip — 다음 gym_id 가 gyms 테이블에 없습니다: %s",
            missing_gyms,
        )

    rows = []
    for r in rows_raw:
        gid = r["gym_id"].strip()
        if gid not in existing_gyms:
            continue
        rows.append(
            {
                "gym_id": uuid.UUID(gid),
                "equipment_id": uuid.UUID(r["equipment_id"].strip()),
                "quantity": int(r.get("quantity", "1") or "1"),
            }
        )

    if not rows:
        logger.warning("gym_equipments: 적재할 행 없음 (모든 gym_id 누락)")
        return 0

    stmt = pg_insert(GymEquipment).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["gym_id", "equipment_id"],
        set_={"quantity": stmt.excluded.quantity},
    )
    await session.execute(stmt)
    logger.info("gym_equipments upsert 완료: %d건", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL 환경변수 없음. server/.env 확인")
        sys.exit(1)

    # asyncpg PgBouncer 호환 (statement_cache_size=0)
    connect_args: dict = {}
    if "postgresql+asyncpg" in database_url or "asyncpg" in database_url:
        connect_args["statement_cache_size"] = 0

    engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session, session.begin():
        # 1) muscle_groups (exercise_muscles FK 의존 — 선행 필수)
        mg_count = await upsert_muscle_groups(session)

        # 2) equipment_brands (equipments.brand_id FK 의존 — equipments 전에 적재)
        brand_count = await upsert_equipment_brands(session)

        # 3) equipments (gym_equipments.equipment_id FK 의존)
        eq_count = await upsert_equipments(session)

        # 4) gym_equipments
        ge_count = await upsert_gym_equipments(session)

    await engine.dispose()

    logger.info(
        "재시드 완료 — muscle_groups=%d, equipment_brands=%d, equipments=%d, gym_equipments=%d",
        mg_count,
        brand_count,
        eq_count,
        ge_count,
    )
    logger.info("다음 단계: python mlops/scripts/seed_exercises_workoutx.py")


if __name__ == "__main__":
    asyncio.run(main())
