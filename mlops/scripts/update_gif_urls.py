"""DB에 있는 exercises.name_en 기준으로 WorkoutX API에서 gif_url만 선택적으로 업데이트.

전체 페이지네이션 대신 이름 검색으로 API 호출을 최소화 (28건 → 28 요청).
Rate limit: 요청 사이 1.5초 대기 + 429 시 지수 백오프 재시도.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
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
_DELAY_BETWEEN = 3.0  # 요청 사이 대기(초) — rate limit 30 req/60s 여유 확보
_RETRY_MAX = 3  # 429 최대 재시도 횟수


async def fetch_gif_by_name(client: httpx.AsyncClient, name_en: str) -> str | None:
    """WorkoutX /exercises/name/{name} 엔드포인트로 gif_url 조회.

    응답 형식: {"total": N, "count": M, "data": [{"id": "...", "name": "...", "gifUrl": "...", ...}, ...]}
    1) 정확히 이름 일치하는 항목 우선 사용
    2) 없으면 첫 번째 항목 사용
    429 → 지수 백오프 재시도.
    """
    url = f"/exercises/name/{name_en}"
    for attempt in range(_RETRY_MAX):
        try:
            resp = await client.get(url)
            if resp.status_code == 429:
                # resetAt 파싱해서 정확한 대기시간 계산
                try:
                    reset_at_str = resp.json().get("resetAt")
                    if reset_at_str:
                        reset_dt = datetime.fromisoformat(reset_at_str.replace("Z", "+00:00"))
                        wait = max(2.0, (reset_dt - datetime.now(timezone.utc)).total_seconds() + 2)
                    else:
                        wait = 65.0
                except Exception:
                    wait = 65.0
                logger.warning(
                    "429 Too Many Requests (%s) — %.0f초 대기 후 재시도 [%d/%d]",
                    name_en,
                    wait,
                    attempt + 1,
                    _RETRY_MAX,
                )
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("HTTP 오류 (%s): %s", name_en, e)
            return None

        payload = resp.json()

        # 응답 형식: {"total": N, "count": M, "data": [...]} 또는 직접 리스트
        if isinstance(payload, dict) and "data" in payload:
            items: list[dict] = payload["data"]
        elif isinstance(payload, list):
            items = payload
        else:
            logger.warning("  ✗ %-40s 알 수 없는 응답 형식: %s", name_en, str(payload)[:80])
            return None

        if not items:
            logger.warning("  ✗ %-40s 검색 결과 없음", name_en)
            return None

        # 첫 번째 항목 키 목록 디버그 (첫 호출에만)
        if not hasattr(fetch_gif_by_name, "_debug_logged"):
            fetch_gif_by_name._debug_logged = True  # type: ignore[attr-defined]
            logger.debug("  [DEBUG] 첫 번째 항목 키: %s", list(items[0].keys()))
            logger.debug("  [DEBUG] 첫 번째 항목 전체: %s", items[0])

        # 정확히 이름 일치하는 항목 우선 (대소문자 무시)
        name_lower = name_en.lower()
        exact = next(
            (it for it in items if it.get("name", "").strip().lower() == name_lower),
            None,
        )
        item = exact or items[0]
        matched_name = item.get("name", "")

        gif_url = item.get("gifUrl")
        if gif_url:
            tag = "(정확)" if exact else "(유사)"
            logger.info(
                "  ✓ %-40s %s → '%s'",
                name_en,
                tag,
                matched_name[:40],
            )
        else:
            logger.warning(
                "  ✗ %-40s gifUrl 없음 (매칭: '%s')",
                name_en,
                matched_name[:40],
            )
        return gif_url

    logger.error("최대 재시도 초과 (%s)", name_en)
    return None


async def main() -> None:
    api_key = os.getenv("WORKOUTX_API_KEY")
    if not api_key:
        logger.error("WORKOUTX_API_KEY 환경변수 없음. server/.env 또는 mlops/.env 확인")
        sys.exit(1)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL 환경변수 없음. server/.env 확인")
        sys.exit(1)

    # Supabase/PgBouncer transaction mode에서 준비된 statement 충돌 방지
    engine = create_async_engine(
        database_url,
        echo=False,
        connect_args={"statement_cache_size": 0},
    )
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ── DB에서 name_en 목록 조회 ──────────────────────────────────────────────
    from app.models.exercise import Exercise  # noqa: E402

    async with factory() as session:
        rows = (await session.execute(select(Exercise.id, Exercise.name_en).where(Exercise.name_en.isnot(None)))).all()

    exercises = [(str(eid), name) for eid, name in rows if name]
    logger.info("DB 조회: name_en 있는 운동 %d개", len(exercises))
    if not exercises:
        logger.info("업데이트할 운동 없음. 종료.")
        await engine.dispose()
        return

    # ── WorkoutX API 호출 (이름별 개별 조회) ─────────────────────────────────
    updates: list[tuple[str, str]] = []  # (exercise_id, gif_url)

    async with httpx.AsyncClient(
        base_url=_BASE_URL,
        headers={"X-WorkoutX-Key": api_key},
        timeout=30.0,
    ) as client:
        for i, (eid, name_en) in enumerate(exercises):
            logger.info("[%d/%d] %s", i + 1, len(exercises), name_en)
            gif_url = await fetch_gif_by_name(client, name_en)
            if gif_url:
                updates.append((eid, gif_url))
            if i < len(exercises) - 1:
                await asyncio.sleep(_DELAY_BETWEEN)

    logger.info("gif_url 확보: %d / %d", len(updates), len(exercises))

    # ── DB 업데이트 ────────────────────────────────────────────────────────────
    if not updates:
        logger.warning("업데이트할 gif_url 없음. DB 변경 없이 종료.")
        await engine.dispose()
        return

    async with factory() as session, session.begin():
        for eid, gif_url in updates:
            await session.execute(update(Exercise).where(Exercise.id == eid).values(gif_url=gif_url))

    logger.info("DB 업데이트 완료: %d건", len(updates))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
