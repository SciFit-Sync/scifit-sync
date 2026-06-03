"""WorkoutX API 프록시 서비스.

운동 GIF 및 상세 정보를 WorkoutX API에서 조회한다.
API 키는 서버 환경변수(WORKOUTX_API_KEY)에만 보관한다.
"""

import logging
import re

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
                return None  # confirmed not-found → sentinel 저장 허용
            logger.error("WorkoutX API HTTP 오류: %s", e)
            raise  # 일시 장애 → sentinel 저장 방지
        except Exception as e:
            logger.error("WorkoutX API 호출 실패: %s", e)
            raise  # 일시 장애 → sentinel 저장 방지


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


def gif_id_from(raw: str | None) -> str | None:
    """저장된 gif_url의 다양한 형태에서 WorkoutX gif id(숫자)를 추출.

    지원: '/static/gifs/0025.gif'(과거 죽은 경로), 'https://api.workoutxapp.com/v1/gifs/0025.gif',
    순수 id '0025'. 추출 불가 시 None.
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    m = re.search(r"(\d+)\.gif", raw)
    if m:
        return m.group(1)
    if raw.isdigit():
        return raw
    return None


def to_gif_proxy_url(raw: str | None, base_url: str) -> str | None:
    """저장된 gif_url을 키 불필요 백엔드 프록시 URL로 변환.

    프론트(<Image>)는 헤더를 못 보내므로, WorkoutX 직링크 대신 서버 프록시 URL을 내려준다.
    id를 못 뽑으면 None(플레이스홀더 표시).
    """
    gid = gif_id_from(raw)
    if not gid:
        return None
    return f"{base_url.rstrip('/')}/api/v1/exercises/gif/{gid}"


async def fetch_gif_bytes(gif_id: str) -> tuple[bytes, str] | None:
    """WorkoutX gif를 서버 API 키로 받아 (bytes, content_type) 반환. 미존재/오류 시 None.

    이미지 로드가 5xx로 실패하지 않도록 모든 오류는 None으로 흡수한다.
    """
    if not gif_id.isdigit():  # SSRF/경로주입 방어
        return None
    if not get_settings().WORKOUTX_API_KEY:
        logger.warning("WORKOUTX_API_KEY 미설정 — gif 프록시 불가")
        return None
    async with _client() as client:
        try:
            resp = await client.get(f"/gifs/{gif_id}.gif")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type", "image/gif")
        except Exception as e:
            logger.error("WorkoutX gif 조회 실패 (id=%s): %s", gif_id, e)
            return None
