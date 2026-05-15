"""핵심 4대 운동(Big 4) 식별 서비스.

온보딩 1RM 설정 화면(W-A04)에서 벤치프레스/스쿼트/데드리프트/오버헤드프레스 4개를
exercise_id 없이 code 기반으로 식별하기 위한 매핑.

⚠️ 현재는 exercises 테이블에 별도 `code` 컬럼이 없어 name_en 기반 fallback.
장기적으로는 exercises 모델에 `code: str` 컬럼 추가 + 마이그레이션 권장.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Exercise

# 4대 운동 code → name_en 후보 리스트 (대소문자 무시, 부분일치)
CORE_LIFTS_NAME_EN_MAP: dict[str, list[str]] = {
    "bench_press": ["Bench Press", "Barbell Bench Press", "Flat Barbell Bench Press"],
    "squat": ["Back Squat", "Barbell Back Squat", "Squat"],
    "deadlift": ["Conventional Deadlift", "Barbell Deadlift", "Deadlift"],
    "overhead_press": ["Overhead Press", "Barbell Overhead Press", "Standing Overhead Press", "Military Press"],
}

# 화면 표시용 한글 라벨 (Figma 1RM 설정 화면)
CORE_LIFTS_KO_LABEL: dict[str, str] = {
    "bench_press": "벤치프레스",
    "squat": "스쿼트",
    "deadlift": "데드리프트",
    "overhead_press": "오버헤드프레스",
}


async def resolve_exercise_id_by_code(code: str, db: AsyncSession) -> uuid.UUID | None:
    """code 문자열로 exercise_id 를 찾는다. 없으면 None.

    매칭 우선순위:
    1. CORE_LIFTS_NAME_EN_MAP[code] 의 후보 이름들과 정확 일치하는 name_en
    2. 그 후보들과 부분 일치(ilike)하는 name_en
    """
    code = code.lower().strip()
    candidates = CORE_LIFTS_NAME_EN_MAP.get(code)
    if not candidates:
        return None

    # 1) 정확 일치
    exact = (await db.execute(select(Exercise.id).where(Exercise.name_en.in_(candidates)))).scalar_one_or_none()
    if exact:
        return exact

    # 2) 부분 일치 (첫 후보 기준)
    for cand in candidates:
        partial = (
            await db.execute(select(Exercise.id).where(Exercise.name_en.ilike(f"%{cand}%")))
        ).scalar_one_or_none()
        if partial:
            return partial

    return None


async def list_core_lifts(db: AsyncSession) -> list[dict]:
    """4대 운동의 (code, exercise_id, name_ko, name_en) 목록 반환.

    DB에서 찾지 못한 code 는 결과에서 제외 (클라이언트 측에서 "준비중" 처리).
    """
    result: list[dict] = []
    for code in CORE_LIFTS_NAME_EN_MAP:
        ex_id = await resolve_exercise_id_by_code(code, db)
        if ex_id is None:
            continue
        row = (await db.execute(select(Exercise.name, Exercise.name_en).where(Exercise.id == ex_id))).one_or_none()
        if row is None:
            continue
        name_ko, name_en = row
        result.append(
            {
                "code": code,
                "exercise_id": str(ex_id),
                "name": CORE_LIFTS_KO_LABEL.get(code, name_ko),
                "name_en": name_en,
            }
        )
    return result
