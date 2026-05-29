"""운동 도메인 엔드포인트.

api-endpoints.md #47, #56.
"""

import logging

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.limiter import rate_limit
from app.models import Exercise, User
from app.schemas.common import SuccessResponse
from app.schemas.users import CoreLiftItem, CoreLiftsData
from app.services.core_lifts import list_core_lifts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exercises", tags=["exercises"])


class ExerciseItem(BaseModel):
    exercise_id: str
    name: str
    name_en: str
    category: str
    gif_url: str | None = None


class ExerciseListData(BaseModel):
    items: list[ExerciseItem]


# ── GET /exercises ────────────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.get("", response_model=SuccessResponse[ExerciseListData], summary="운동 목록 조회")
async def list_exercises(
    request: Request,
    keyword: str | None = Query(None),
    category: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Exercise)
    if keyword:
        q = q.where(Exercise.name.ilike(f"%{keyword}%") | Exercise.name_en.ilike(f"%{keyword}%"))
    if category:
        q = q.where(Exercise.category == category)
    q = q.order_by(Exercise.name)

    exercises = (await db.execute(q)).scalars().all()
    items = [
        ExerciseItem(
            exercise_id=str(e.id),
            name=e.name,
            name_en=e.name_en,
            category=e.category,
            gif_url=e.gif_url,
        )
        for e in exercises
    ]
    return SuccessResponse(data=ExerciseListData(items=items))


# ── GET /exercises/core-lifts ─────────────────────────────────────────────────
@rate_limit("60/minute")
@router.get(
    "/core-lifts",
    response_model=SuccessResponse[CoreLiftsData],
    summary="핵심 4대 운동 식별자 조회",
)
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
