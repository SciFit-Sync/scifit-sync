"""운동 도메인 엔드포인트.

api-endpoints.md #47, #56.
"""

import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.limiter import rate_limit
from app.models import Exercise, ExerciseMuscle, MuscleGroup, MuscleInvolvement, User
from app.schemas.common import SuccessResponse
from app.schemas.users import CoreLiftItem, CoreLiftsData
from app.services.core_lifts import list_core_lifts
from app.services.workoutx import fetch_gif_bytes, to_gif_proxy_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exercises", tags=["exercises"])


class ExerciseItem(BaseModel):
    exercise_id: str
    name: str
    name_en: str
    category: str
    gif_url: str | None = None
    primary_muscle_groups: list[str] = []


class ExerciseListData(BaseModel):
    items: list[ExerciseItem]
    total_count: int
    page: int


# ── GET /exercises ────────────────────────────────────────────────────────────
@router.get("", response_model=SuccessResponse[ExerciseListData], summary="운동 목록 조회")
@rate_limit("60/minute")
async def list_exercises(
    request: Request,
    keyword: str | None = Query(None),
    category: str | None = Query(None),
    muscle: str | None = Query(None),
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base_q = select(Exercise)
    if keyword:
        base_q = base_q.where(Exercise.name.ilike(f"%{keyword}%") | Exercise.name_en.ilike(f"%{keyword}%"))
    if category:
        base_q = base_q.where(Exercise.category == category)
    if muscle:
        muscle_ids = (
            select(ExerciseMuscle.exercise_id)
            .join(MuscleGroup, ExerciseMuscle.muscle_group_id == MuscleGroup.id)
            .where(MuscleGroup.name_ko.ilike(f"%{muscle}%"))
        )
        base_q = base_q.where(Exercise.id.in_(muscle_ids))

    # 1) total_count
    count_q = select(func.count()).select_from(base_q.subquery())
    total_count = (await db.execute(count_q)).scalar_one()

    # 2) exercises (paginated)
    items_q = base_q.order_by(Exercise.name).offset(page * size).limit(size)
    exercises = (await db.execute(items_q)).scalars().unique().all()

    if not exercises:
        return SuccessResponse(data=ExerciseListData(items=[], total_count=total_count, page=page))

    exercise_ids = [e.id for e in exercises]

    # 3) muscle rows
    muscle_q = (
        select(ExerciseMuscle.exercise_id, ExerciseMuscle.involvement, MuscleGroup.name_ko)
        .join(MuscleGroup, ExerciseMuscle.muscle_group_id == MuscleGroup.id)
        .where(ExerciseMuscle.exercise_id.in_(exercise_ids))
    )
    muscle_rows = (await db.execute(muscle_q)).all()

    # Build primary_muscle_groups map
    primary_map: dict = defaultdict(list)
    for ex_id, involvement, muscle_name in muscle_rows:
        if involvement == MuscleInvolvement.PRIMARY:
            primary_map[ex_id].append(muscle_name)

    items = [
        ExerciseItem(
            exercise_id=str(e.id),
            name=e.name,
            name_en=e.name_en,
            category=e.category,
            gif_url=to_gif_proxy_url(e.gif_url, get_settings().PUBLIC_BASE_URL),
            primary_muscle_groups=primary_map.get(e.id, []),
        )
        for e in exercises
    ]
    return SuccessResponse(data=ExerciseListData(items=items, total_count=total_count, page=page))


# ── GET /exercises/core-lifts ─────────────────────────────────────────────────
@router.get(
    "/core-lifts",
    response_model=SuccessResponse[CoreLiftsData],
    summary="핵심 4대 운동 식별자 조회",
)
@rate_limit("60/minute")
async def get_core_lifts(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lifts = await list_core_lifts(db)
    items = [
        CoreLiftItem(
            code=lift["code"],
            exercise_id=lift["exercise_id"],
            name=lift["name"],
            name_en=lift.get("name_en"),
        )
        for lift in lifts
    ]
    return SuccessResponse(data=CoreLiftsData(items=items))


# ── GET /exercises/gif/{gif_id} ───────────────────────────────────────────────
@router.get("/gif/{gif_id}", summary="운동 GIF 프록시 (WorkoutX 인증 우회)")
async def proxy_exercise_gif(gif_id: str) -> Response:
    """WorkoutX gif를 서버 API 키로 받아 스트리밍한다.

    프론트 <Image>는 헤더를 못 보내므로 키 없는 이 프록시 URL을 쓴다. 키는 서버에만 남는다.
    인증 불요(공개 이미지 콘텐츠) — 유저 토큰 만료와 무관하게 gif가 로드된다.
    rate_limit 미적용: limiter가 ALB IP로 키잉돼 사실상 전역이라, 한 화면이 여러 gif를
    동시 로드할 때 throttle 위험이 있기 때문. 남용 방지는 Cache-Control + (후속) 서버 캐시로.
    """
    res = await fetch_gif_bytes(gif_id)
    if res is None:
        raise NotFoundError(message="GIF를 찾을 수 없습니다")
    content, content_type = res
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=2592000, immutable"},
    )
