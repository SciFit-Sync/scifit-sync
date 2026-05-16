"""Gemini 기반 기구 이미지 생성 서비스.

image_url 이 DB에 없을 때 Gemini로 이미지를 생성해 로컬 static 디렉토리에 캐싱한다.
이후 요청에서는 캐시된 파일을 그대로 사용한다.
GEMINI_API_KEY 가 설정되지 않으면 아무 동작 없이 None 을 반환한다.
"""

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parents[2] / "static" / "equipment_images"
_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_IMAGE_MODEL = "gemini-2.0-flash-preview-image-generation"


def _generate_sync(equipment_id: str, name: str, name_en: str | None) -> str | None:
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=_GEMINI_API_KEY)
        prompt = (
            f"Professional gym equipment product photo: {name_en or name}. "
            "Clean white background, studio lighting, high quality."
        )
        response = client.models.generate_content(
            model=_IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                _STATIC_DIR.mkdir(parents=True, exist_ok=True)
                cached_path = _STATIC_DIR / f"{equipment_id}.png"
                cached_path.write_bytes(part.inline_data.data)
                logger.info("이미지 생성 완료: %s", equipment_id)
                return f"/static/equipment_images/{equipment_id}.png"
    except Exception as e:
        logger.warning("이미지 생성 실패 (equipment_id=%s): %s", equipment_id, e)
    return None


async def get_or_generate_image_url(
    equipment_id: str, name: str, name_en: str | None
) -> str | None:
    """기구 이미지 URL 반환. 캐시에 없으면 Gemini로 생성 후 저장."""
    cached_path = _STATIC_DIR / f"{equipment_id}.png"
    if cached_path.exists():
        return f"/static/equipment_images/{equipment_id}.png"

    if not _GEMINI_API_KEY:
        return None

    return await asyncio.to_thread(_generate_sync, equipment_id, name, name_en)
