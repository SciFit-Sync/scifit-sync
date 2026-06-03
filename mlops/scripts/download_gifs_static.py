"""DB의 gif_url(WorkoutX URL)을 다운로드해서 server/static/gifs/ 에 저장하고
DB gif_url을 상대 경로 /static/gifs/XXXX.gif 로 업데이트.

이후 FastAPI /static/gifs/XXXX.gif 로 공개 서빙되므로
React Native <Image source={{ uri: ... }}> 에서 인증 없이 표시 가능.
"""

import asyncio
import logging
import os
import re
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

STATIC_GIFS_DIR = REPO_ROOT / "server" / "static" / "gifs"
_DELAY = 0.5  # 초 단위 (static 서버 다운로드는 rate limit 덜 엄격)
_RETRY_MAX = 3


def extract_gif_filename(url: str) -> str | None:
    """https://api.workoutxapp.com/v1/gifs/0031.gif → 0031.gif"""
    m = re.search(r"/gifs/([^/?#]+\.gif)$", url, re.IGNORECASE)
    return m.group(1) if m else None


async def download_gif(client: httpx.AsyncClient, url: str, dest: Path) -> bool:
    """gif 다운로드. 성공 여부 반환."""
    for _attempt in range(_RETRY_MAX):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                return True
            if resp.status_code == 429:
                wait = 65.0
                logger.warning("429 Rate limit (%s) — %.0f초 대기", url, wait)
                await asyncio.sleep(wait)
                continue
            logger.warning("다운로드 실패 status=%d (%s)", resp.status_code, url)
            return False
        except Exception as e:
            logger.error("다운로드 예외 (%s): %s", url, e)
            return False
    return False


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

    # gif_url이 있고 아직 WorkoutX URL인 운동들 조회
    async with factory() as session:
        rows = (
            await session.execute(
                select(Exercise.id, Exercise.name_en, Exercise.gif_url)
                .where(Exercise.gif_url.isnot(None))
                .where(Exercise.gif_url.like("https://api.workoutxapp.com%"))
            )
        ).all()

    targets = [(str(eid), name, url) for eid, name, url in rows]
    logger.info("WorkoutX URL gif_url 운동: %d개 다운로드 시작", len(targets))

    STATIC_GIFS_DIR.mkdir(parents=True, exist_ok=True)

    updates: list[tuple[str, str]] = []  # (exercise_id, new_relative_url)

    async with httpx.AsyncClient(
        headers={"X-WorkoutX-Key": api_key},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        for i, (eid, name_en, gif_url) in enumerate(targets):
            filename = extract_gif_filename(gif_url)
            if not filename:
                logger.warning("[%d/%d] %-35s 파일명 추출 실패: %s", i + 1, len(targets), name_en, gif_url)
                continue

            dest = STATIC_GIFS_DIR / filename
            if dest.exists():
                logger.info("[%d/%d] %-35s 이미 있음 → skip", i + 1, len(targets), name_en)
            else:
                logger.info("[%d/%d] %-35s 다운로드 중...", i + 1, len(targets), name_en)
                ok = await download_gif(client, gif_url, dest)
                if not ok:
                    logger.error("  FAIL: %s", gif_url)
                    continue
                logger.info("  OK: %s (%.1f KB)", filename, dest.stat().st_size / 1024)
                await asyncio.sleep(_DELAY)

            updates.append((eid, f"/static/gifs/{filename}"))

    logger.info("다운로드 완료 — DB 업데이트: %d건", len(updates))

    if updates:
        async with factory() as session, session.begin():
            for eid, relative_url in updates:
                await session.execute(update(Exercise).where(Exercise.id == eid).values(gif_url=relative_url))
        logger.info("DB gif_url → 상대경로 변경 완료")

    await engine.dispose()
    logger.info("전체 완료. static/gifs 파일 수: %d", len(list(STATIC_GIFS_DIR.glob("*.gif"))))


if __name__ == "__main__":
    asyncio.run(main())
