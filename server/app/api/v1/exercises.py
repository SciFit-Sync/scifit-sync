"""운동 카탈로그 엔드포인트 (#47 GET /exercises)."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models import (
    Exercise,
    ExerciseMuscle,
    MuscleGroup,
    MuscleInvolvement,
    User,
)
from app.schemas.common import SuccessResponse
from app.schemas.gyms import ExerciseItem, ExerciseListData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exercises", tags=["exercises"])


@router.get("", response_model=SuccessResponse[ExerciseListData], summary="운동 목록")
async def list_exercises(
    keyword: str | None = Query(None),
    category: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Exercise).options(selectinload(Exercise.muscle_maps))
    if keyword:
        stmt = stmt.where(Exercise.name.ilike(f"%{keyword}%"))
    if category:
        stmt = stmt.where(Exercise.category == category)

    exercises = (await db.execute(stmt)).scalars().unique().all()

    # primary muscle group names per exercise
    primary_map: dict[str, list[str]] = {}
    if exercises:
        ex_ids = [e.id for e in exercises]
        muscle_rows = (
            await db.execute(
                select(ExerciseMuscle, MuscleGroup.name_ko)
                .join(MuscleGroup, ExerciseMuscle.muscle_group_id == MuscleGroup.id)
                .where(
                    ExerciseMuscle.exercise_id.in_(ex_ids),
                    ExerciseMuscle.involvement == MuscleInvolvement.PRIMARY,
                )
            )
        ).all()
        for em, name_ko in muscle_rows:
            primary_map.setdefault(str(em.exercise_id), []).append(name_ko)

    items = [
        ExerciseItem(
            exercise_id=str(e.id),
            name=e.name,
            name_en=e.name_en,
            description=e.description,
            image_url=None,
            primary_muscle_groups=primary_map.get(str(e.id), []),
        )
        for e in exercises
    ]
    return SuccessResponse(data=ExerciseListData(items=items))
