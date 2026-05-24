"""WorkoutX API → exercises 테이블 교체 스크립트.

WorkoutX에서 전체 운동 목록을 받아:
  1. exercises 테이블을 name_en 기준으로 upsert (gif_url 포함)
  2. exercise_equipment_map을 WorkoutX equipment → equipments.equipment_type 매핑으로 자동 생성

cardiovascular system target은 제외한다.

사용법:
    # server/.env의 DATABASE_URL과 WORKOUTX_API_KEY 필요
    # 레포 루트에서 실행:
    mlops\\.venv\\Scripts\\activate
    python mlops/scripts/seed_exercises_workoutx.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / "mlops" / ".env")
load_dotenv(REPO_ROOT / "server" / ".env", override=True)

import httpx  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger(__name__)

_BASE_URL = "https://api.workoutxapp.com/v1"
_PAGE_SIZE = 100

# WorkoutX target → DB category
WORKOUTX_TARGET_TO_CATEGORY: dict[str, str] = {
    "pectorals": "chest",
    "serratus anterior": "chest",
    "lats": "back",
    "traps": "back",
    "upper back": "back",
    "levator scapulae": "back",
    "spine": "back",
    "delts": "shoulders",
    "biceps": "arms",
    "triceps": "arms",
    "forearms": "arms",
    "abs": "core",
    "glutes": "legs",
    "hamstrings": "legs",
    "quads": "legs",
    "calves": "legs",
    "adductors": "legs",
    "abductors": "legs",
}

# WorkoutX equipment → equipments.equipment_type
WORKOUTX_EQUIPMENT_TO_TYPE: dict[str, str] = {
    "barbell": "barbell",
    "ez barbell": "barbell",
    "trap bar": "barbell",
    "cable": "cable",
    "dumbbell": "dumbbell",
    "body weight": "bodyweight",
    "machine": "machine",
    "leverage machine": "machine",
    "smith machine": "machine",
    "assisted": "machine",
}


async def fetch_all_exercises(api_key: str) -> list[dict]:
    """WorkoutX API에서 전체 운동 목록 페이지네이션으로 가져오기."""
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


async def upsert_exercises(session: AsyncSession, exercises: list[dict]) -> int:
    """exercises 테이블 upsert. 처리 건수 반환."""
    from app.models.exercise import Exercise  # noqa: E402

    rows = []
    for ex in exercises:
        target = ex.get("target", "")
        category = WORKOUTX_TARGET_TO_CATEGORY.get(target)
        if not category:
            continue

        name_en = ex.get("name", "").strip()
        if not name_en:
            continue

        rows.append(
            {
                "name": name_en,
                "name_en": name_en,
                "category": category,
                "gif_url": ex.get("gifUrl"),
            }
        )

    if not rows:
        return 0

    stmt = pg_insert(Exercise).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["name_en"],
        set_={
            "name": stmt.excluded.name,
            "category": stmt.excluded.category,
            "gif_url": stmt.excluded.gif_url,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_equipment_map(
    session: AsyncSession,
    exercises: list[dict],
    eq_by_type: dict[str, list],
) -> int:
    """exercise_equipment_map을 equipment_type 기준으로 자동 생성. 생성 건수 반환."""
    from app.models.exercise import Exercise, ExerciseEquipmentMap  # noqa: E402

    count = 0
    for ex in exercises:
        target = ex.get("target", "")
        if not WORKOUTX_TARGET_TO_CATEGORY.get(target):
            continue

        name_en = ex.get("name", "").strip()
        eq_type = WORKOUTX_EQUIPMENT_TO_TYPE.get(ex.get("equipment", ""))
        if not eq_type or not name_en:
            continue

        result = await session.execute(select(Exercise.id).where(Exercise.name_en == name_en))
        exercise_id = result.scalar_one_or_none()
        if not exercise_id:
            continue

        for eq_id in eq_by_type.get(eq_type, []):
            stmt = (
                pg_insert(ExerciseEquipmentMap)
                .values(
                    exercise_id=exercise_id,
                    equipment_id=eq_id,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
            count += 1

    return count


async def main() -> None:
    api_key = os.getenv("WORKOUTX_API_KEY")
    if not api_key:
        logger.error("WORKOUTX_API_KEY 환경변수 없음. server/.env 또는 mlops/.env 확인")
        sys.exit(1)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL 환경변수 없음. server/.env 확인")
        sys.exit(1)

    logger.info("WorkoutX에서 운동 목록 수집 시작")
    exercises = await fetch_all_exercises(api_key)
    logger.info("총 %d개 운동 수집 완료", len(exercises))

    engine = create_async_engine(database_url, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        # equipments 테이블에서 equipment_type별 id 목록 로드
        result = await session.execute(
            text("SELECT id, equipment_type FROM equipments WHERE equipment_type IS NOT NULL")
        )
        eq_by_type: dict[str, list] = {}
        for row in result:
            eq_by_type.setdefault(row.equipment_type, []).append(row.id)
        logger.info("equipments 로드: %s", {k: len(v) for k, v in eq_by_type.items()})

        ex_count = await upsert_exercises(session, exercises)
        await session.commit()
        logger.info("exercises upsert 완료: %d건", ex_count)

        map_count = await upsert_equipment_map(session, exercises, eq_by_type)
        await session.commit()
        logger.info("exercise_equipment_map 생성 완료: %d건", map_count)

    await engine.dispose()
    logger.info("완료. exercises %d건, exercise_equipment_map %d건", ex_count, map_count)


if __name__ == "__main__":
    asyncio.run(main())
