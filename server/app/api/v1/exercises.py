"""운동 카탈로그 엔드포인트 (#47 GET /exercises)."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models import (
    Exercise,
    ExerciseEquipmentMap,
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
    keyword: str | None = Query(None, description="운동 이름 키워드 검색"),
    muscle: str | None = Query(None, description="근육 그룹 영문명 (name_en) 필터"),
    page: int = Query(0, ge=0, description="페이지 번호 (0-based)"),
    size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Exercise)

    if keyword:
        stmt = stmt.where(Exercise.name.ilike(f"%{keyword}%"))

    if muscle:
        muscle_ex_subq = (
            select(ExerciseMuscle.exercise_id)
            .join(MuscleGroup, ExerciseMuscle.muscle_group_id == MuscleGroup.id)
            .where(MuscleGroup.name_en == muscle)
        )
        stmt = stmt.where(Exercise.id.in_(muscle_ex_subq))

    total_count: int = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    total_pages = (total_count + size - 1) // size

    stmt = stmt.order_by(Exercise.name).offset(page * size).limit(size)
    exercises = (await db.execute(stmt)).scalars().unique().all()

    if not exercises:
        return SuccessResponse(
            data=ExerciseListData(items=[], total_count=total_count, page=page, total_pages=total_pages)
        )

    ex_ids = [e.id for e in exercises]

    # primary / secondary 근육 그룹
    muscle_rows = (
        await db.execute(
            select(ExerciseMuscle.exercise_id, ExerciseMuscle.involvement, MuscleGroup.name_ko)
            .join(MuscleGroup, ExerciseMuscle.muscle_group_id == MuscleGroup.id)
            .where(
                ExerciseMuscle.exercise_id.in_(ex_ids),
                ExerciseMuscle.involvement.in_([MuscleInvolvement.PRIMARY, MuscleInvolvement.SECONDARY]),
            )
        )
    ).all()

    primary_map: dict[str, list[str]] = {}
    secondary_map: dict[str, list[str]] = {}
    for ex_id, involvement, name_ko in muscle_rows:
        key = str(ex_id)
        if involvement == MuscleInvolvement.PRIMARY:
            primary_map.setdefault(key, []).append(name_ko)
        else:
            secondary_map.setdefault(key, []).append(name_ko)

    # 종목별 첫 번째 equipment_id
    eq_rows = (
        await db.execute(
            select(ExerciseEquipmentMap.exercise_id, ExerciseEquipmentMap.equipment_id)
            .where(ExerciseEquipmentMap.exercise_id.in_(ex_ids))
        )
    ).all()

    eq_map: dict[str, str] = {}
    for ex_id, eq_id in eq_rows:
        key = str(ex_id)
        if key not in eq_map:
            eq_map[key] = str(eq_id)

    items = [
        ExerciseItem(
            exercise_id=str(e.id),
            name=e.name,
            name_en=e.name_en,
            primary_muscle_groups=primary_map.get(str(e.id), []),
            secondary_muscle_groups=secondary_map.get(str(e.id), []),
            equipment_id=eq_map.get(str(e.id)),
        )
        for e in exercises
    ]
    return SuccessResponse(
        data=ExerciseListData(items=items, total_count=total_count, page=page, total_pages=total_pages)
    )
