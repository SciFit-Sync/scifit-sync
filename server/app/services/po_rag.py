"""RAG 기반 Progressive Overload 증가량 추출 서비스.

ChromaDB에서 load_progression 논문 청크를 검색하고,
LLM이 % 증가량을 추출한 뒤 사용자 1RM 기반 kg로 변환한다.

실패(논문 없음, LLM 오류, 1RM 없음 등) 시 None 반환 → po.py 하드코딩 fallback.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# llm.py 동일 디렉터리 직접 import (rag.py 동일 패턴)
_SERVICES_DIR = Path(__file__).resolve().parent
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))
from llm import generate as _llm_generate  # noqa: E402

# (goal, equipment_type) → (increment_percent_or_none, expires_at_monotonic)
_cache: dict[tuple[str, str], tuple[float | None, float]] = {}
_CACHE_TTL = 604800.0  # 7d (논문 DB 업데이트 주기: 월 1회)


# ── 캐시 헬퍼 ─────────────────────────────────────────────────────────────────

def _cache_get(goal: str, equipment_type: str) -> tuple[bool, float | None]:
    entry = _cache.get((goal, equipment_type))
    if entry is None:
        return False, None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        del _cache[(goal, equipment_type)]
        return False, None
    return True, value


def _cache_set(goal: str, equipment_type: str, value: float | None) -> None:
    _cache[(goal, equipment_type)] = (value, time.monotonic() + _CACHE_TTL)


# ── 변환 헬퍼 ─────────────────────────────────────────────────────────────────

def _convert_to_kg(increment_percent: float, user_1rm_kg: float) -> float:
    """% → 2.5kg 단위 반올림, [1.25, 10.0] kg 클램핑."""
    raw = user_1rm_kg * (increment_percent / 100.0)
    rounded = round(raw / 2.5) * 2.5
    return max(1.25, min(10.0, rounded))


def _build_prompt(goal: str, equipment_type: str, chunks: list[dict]) -> str:
    excerpts = "\n---\n".join(c.get("document", "") for c in chunks[:3])
    return (
        "<system>\n"
        "You are a sports science expert. Based ONLY on the provided paper excerpts, "
        'return a single JSON object with one key: "increment_percent" (number or null). '
        "This represents the recommended per-session weight increase as a percentage of "
        f"current working weight for {goal} training. "
        "If the papers do not contain enough evidence, "
        'return {"increment_percent": null}.\n'
        "</system>\n\n"
        "<paper_excerpts>\n"
        f"{excerpts}\n"
        "</paper_excerpts>\n\n"
        "<user_query>\n"
        f"Equipment type: {equipment_type}\n"
        f"Training goal: {goal}\n"
        "What percentage weight increase per session do these papers support?\n"
        "</user_query>"
    )


# ── 비동기 래퍼 (테스트 모킹 포인트) ─────────────────────────────────────────

async def _call_search_async(query: str, top_k: int) -> list[dict]:
    from app.services.rag import search_chunks
    return await asyncio.to_thread(search_chunks, query, top_k)


async def _call_llm_async(prompt: str) -> str:
    return await asyncio.to_thread(_llm_generate, prompt)


# ── 공개 API ──────────────────────────────────────────────────────────────────

async def rag_po_increment(
    goal: str,
    equipment_type: str,
    user_1rm_kg: float | None,
) -> float | None:
    """논문 기반 세션당 증가량(kg) 반환. 실패·논문 없음·1RM 없음 시 None."""
    hit, cached_pct = _cache_get(goal, equipment_type)
    if hit:
        if cached_pct is None or user_1rm_kg is None:
            return None
        return _convert_to_kg(cached_pct, user_1rm_kg)

    try:
        query = (
            f"{goal} resistance training progressive overload "
            "weight increment recommendation"
        )
        chunks = await _call_search_async(query, 3)

        if not chunks:
            _cache_set(goal, equipment_type, None)
            return None

        prompt = _build_prompt(goal, equipment_type, chunks)
        raw = await _call_llm_async(prompt)

        parsed = json.loads(raw.strip())
        pct = parsed.get("increment_percent")

        if pct is None or not isinstance(pct, (int, float)):
            _cache_set(goal, equipment_type, None)
            return None

        pct_float = float(pct)
        _cache_set(goal, equipment_type, pct_float)

        if user_1rm_kg is None:
            return None
        return _convert_to_kg(pct_float, user_1rm_kg)

    except Exception:
        logger.warning(
            "rag_po_increment failed for goal=%s equipment_type=%s",
            goal,
            equipment_type,
        )
        return None
