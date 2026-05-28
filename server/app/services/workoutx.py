"""WorkoutX API 프록시 서비스.

운동 GIF 및 상세 정보를 WorkoutX API에서 조회한다.
API 키는 서버 환경변수(WORKOUTX_API_KEY)에만 보관한다.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.workoutxapp.com/v1"
_TIMEOUT = 10.0


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=_BASE_URL,
        headers={"X-WorkoutX-Key": settings.WORKOUTX_API_KEY},
        timeout=_TIMEOUT,
    )


async def get_exercise_by_name(name_en: str) -> dict | None:
    """운동 영문명으로 WorkoutX 운동 정보(gifUrl 포함) 조회.

    Returns None when not found or API unavailable.
    """
    if not get_settings().WORKOUTX_API_KEY:
        logger.warning("WORKOUTX_API_KEY 미설정 — WorkoutX API 호출 건너뜀")
        return None

    async with _client() as client:
        try:
            resp = await client.get(f"/exercises/name/{name_en}")
            resp.raise_for_status()
            data = resp.json()
            # { total, count, data: [...] } 래퍼 구조 처리
            if isinstance(data, dict) and "data" in data:
                items = data["data"]
                return items[0] if items else None
            # 배열로 직접 반환하는 경우 대비
            if isinstance(data, list):
                return data[0] if data else None
            return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error("WorkoutX API HTTP 오류: %s", e)
            return None
        except Exception as e:
            logger.error("WorkoutX API 호출 실패: %s", e)
            return None


async def get_exercise_gif(name_en: str) -> str | None:
    """운동 영문명으로 GIF URL만 반환. 없으면 None."""
    data = await get_exercise_by_name(name_en)
    if data:
        return data.get("gifUrl")
    return None


async def list_all_exercises(limit_per_page: int = 100) -> list[dict]:
    """WorkoutX 전체 운동 목록 페이징 조회."""
    if not get_settings().WORKOUTX_API_KEY:
        logger.warning("WORKOUTX_API_KEY 미설정 — WorkoutX API 호출 건너뜀")
        return []

    all_items: list[dict] = []
    offset = 0
    async with _client() as client:
        while True:
            try:
                resp = await client.get("/exercises", params={"limit": limit_per_page, "offset": offset})
                resp.raise_for_status()
                data = resp.json()
                items: list[dict] = data.get("data") if isinstance(data, dict) else data
                if not isinstance(items, list) or not items:
                    break
                all_items.extend(items)
                if len(items) < limit_per_page:
                    break
                offset += limit_per_page
            except Exception as e:
                logger.error("WorkoutX 전체 목록 조회 실패 (offset=%d): %s", offset, e)
                break
    logger.info("WorkoutX 전체 운동 목록 조회 완료: %d개", len(all_items))
    return all_items
