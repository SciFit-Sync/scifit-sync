"""gif_url이 없는 운동들에 대해 대체 이름으로 WorkoutX에서 검색 후 DB 업데이트.

update_gif_urls.py 이후 여전히 gif_url이 없는 운동에 대해
WorkoutX에서 사용하는 다른 이름으로 재시도.
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
from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger(__name__)

_BASE_URL = "https://api.workoutxapp.com/v1"
_DELAY = 3.0
_RETRY_MAX = 3

# DB에 저장된 name_en → WorkoutX에서 검색할 대체 이름들 (우선순위 순)
ALTERNATE_NAMES: dict[str, list[str]] = {
    "Back Squat":              ["Barbell Squat", "Barbell Back Squat"],
    "Barbell Row":             ["Bent Over Barbell Row", "Barbell Bent Over Row", "Bent-Over Barbell Row"],
    "Side Lateral Raise":      ["Dumbbell Lateral Raise", "Lateral Raise", "Dumbbell Side Lateral Raise"],
    "Face Pull":               ["Cable Face Pull", "Cable Pull Through"],
    "Dumbbell Shoulder Press": ["Seated Dumbbell Shoulder Press", "Dumbbell Seated Shoulder Press", "Arnold Press"],
    "Seated Cable Row":        ["Cable Seated Row", "Seated Row", "Cable Row"],
    "Dumbbell Curl":           ["Dumbbell Alternate Bicep Curl", "Dumbbell Bicep Curl", "Alternating Dumbbell Curl"],
    "Conventional Deadlift":   ["Barbell Deadlift"],
    "Cable Fly":               ["Cable Crossover Fly", "Cable Chest Fly", "Low Cable Crossover"],
    "Cable Crunch":            ["Kneeling Cable Crunch", "Cable Kneeling Crunch"],
    "Chest Press Machine":     ["Machine Chest Press", "Lever Chest Press"],
    "Pec Deck Fly":            ["Pec Deck", "Chest Fly Machine", "Lever Pec Deck Fly"],
    "Cable Crossover":         ["Cable Crossover Chest", "High Cable Crossover"],
    "One-Arm Dumbbell Row":    ["Dumbbell One Arm Row", "Single Arm Dumbbell Row"],
    "Rear Delt Fly":           ["Dumbbell Rear Delt Fly", "Reverse Fly", "Bent Over Reverse Fly"],
    "Incline Dumbbell Curl":   ["Dumbbell Incline Curl", "Incline Hammer Curl"],
    "Bulgarian Split Squat":   ["Dumbbell Bulgarian Split Squat", "Split Squat"],
    "Ab Rollout":              ["Ab Wheel Rollout", "Wheel Rollout", "Ab Roller"],
}


async def search_by_name(client: httpx.AsyncClient, name: str) -> dict | None:
    """이름으로 첫 번째 매칭 운동 반환. 429 시 대기 후 재시도."""
    from datetime import datetime, timezone

    for _attempt in range(_RETRY_MAX):
        try:
            resp = await client.get(f"/exercises/name/{name}")
        except Exception as e:
            logger.error("요청 실패 (%s): %s", name, e)
            return None

        if resp.status_code == 429:
            try:
                reset_str = resp.json().get("resetAt")
                wait = max(5.0, (datetime.fromisoformat(reset_str.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() + 3) if reset_str else 65.0
            except Exception:
                wait = 65.0
            logger.warning("429 (%s) — %.0f초 대기", name, wait)
            await asyncio.sleep(wait)
            continue

        if resp.status_code != 200:
            return None

        data = resp.json()
        items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return items[0] if items else None

    return None


async def main() -> None:
    api_key = os.getenv("WORKOUTX_API_KEY")
    if not api_key:
        logger.error("WORKOUTX_API_KEY 환경변수 없음")
        sys.exit(1)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL 환경변수 없음")
        sys.exit(1)

    engine = create_async_engine(database_url, echo=False, connect_args={"statement_cache_size": 0})
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from app.models.exercise import Exercise  # noqa: E402

    # gif_url이 없는 운동들만 대상으로 선택
    async with factory() as session:
        rows = (
            await session.execute(
                select(Exercise.id, Exercise.name_en)
                .where(Exercise.name_en.isnot(None))
                .where(Exercise.gif_url.is_(None))
            )
        ).all()

    targets = {str(eid): name for eid, name in rows}
    logger.info("gif_url 없는 운동: %d개", len(targets))

    updates: list[tuple[str, str]] = []

    async with httpx.AsyncClient(
        base_url=_BASE_URL,
        headers={"X-WorkoutX-Key": api_key},
        timeout=15.0,
    ) as client:
        done = 0
        for eid, name_en in targets.items():
            alts = ALTERNATE_NAMES.get(name_en, [])
            if not alts:
                logger.info("  SKIP %-40s (대체 이름 없음)", name_en)
                continue

            found = False
            for alt in alts:
                logger.info("  시도 %-40s → '%s'", name_en, alt)
                item = await search_by_name(client, alt)
                done += 1
                if item:
                    gif_url = item.get("gifUrl")
                    if gif_url:
                        logger.info("    ✓ 매칭: '%s' | gif=%s", item.get("name", ""), gif_url[:50] + "…")
                        updates.append((eid, gif_url))
                        found = True
                        break
                    else:
                        logger.warning("    ~ '%s' 찾았지만 gifUrl 없음", item.get("name", ""))
                else:
                    logger.warning("    ✗ 결과 없음")

                await asyncio.sleep(_DELAY)

            if not found:
                logger.warning("  FAIL %-40s 모든 대체 이름 실패", name_en)

    logger.info("gif_url 확보: %d개", len(updates))

    if updates:
        async with factory() as session, session.begin():
            for eid, gif_url in updates:
                await session.execute(update(Exercise).where(Exercise.id == eid).values(gif_url=gif_url))
        logger.info("DB 업데이트 완료: %d건", len(updates))
    else:
        logger.info("업데이트 없음")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
