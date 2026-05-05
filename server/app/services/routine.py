import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.routine import RoutineExercise, RoutinePaper, WorkoutRoutine

logger = logging.getLogger(__name__)


async def get_routine_or_404(db: AsyncSession, routine_id: uuid.UUID, user_id: uuid.UUID) -> WorkoutRoutine:
    result = await db.execute(
        select(WorkoutRoutine)
        .where(WorkoutRoutine.id == routine_id, WorkoutRoutine.deleted_at.is_(None))
        .options(
            selectinload(WorkoutRoutine.days).selectinload(
                WorkoutRoutine.days.property.mapper.class_.exercises
            ).selectinload(RoutineExercise.exercise),
            selectinload(WorkoutRoutine.days).selectinload(
                WorkoutRoutine.days.property.mapper.class_.exercises
            ).selectinload(RoutineExercise.equipment),
            selectinload(WorkoutRoutine.papers),
        )
    )
    routine = result.scalar_one_or_none()
    if not routine:
        raise NotFoundError("해당 루틴을 찾을 수 없습니다.")
    if routine.user_id != user_id:
        raise ForbiddenError("해당 루틴에 접근할 권한이 없습니다.")
    return routine


async def list_routines(
    db: AsyncSession,
    user_id: uuid.UUID,
    goal: str | None,
    page: int,
    size: int,
) -> tuple[list[WorkoutRoutine], int]:
    base_query = select(WorkoutRoutine).where(
        WorkoutRoutine.user_id == user_id,
        WorkoutRoutine.deleted_at.is_(None),
    )
    if goal:
        base_query = base_query.where(WorkoutRoutine.fitness_goal == goal.lower())

    count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = count_result.scalar_one()

    result = await db.execute(
        base_query.options(
            selectinload(WorkoutRoutine.days).selectinload(
                WorkoutRoutine.days.property.mapper.class_.exercises
            ),
            selectinload(WorkoutRoutine.papers),
        )
        .order_by(WorkoutRoutine.created_at.desc())
        .offset(page * size)
        .limit(size)
    )
    routines = list(result.scalars().all())
    return routines, total


async def get_routine_detail(
    db: AsyncSession,
    routine_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkoutRoutine:
    result = await db.execute(
        select(WorkoutRoutine)
        .where(WorkoutRoutine.id == routine_id, WorkoutRoutine.deleted_at.is_(None))
        .options(
            selectinload(WorkoutRoutine.days).selectinload(
                WorkoutRoutine.days.property.mapper.class_.exercises
            ).selectinload(RoutineExercise.exercise),
            selectinload(WorkoutRoutine.days).selectinload(
                WorkoutRoutine.days.property.mapper.class_.exercises
            ).selectinload(RoutineExercise.equipment).selectinload(
                RoutineExercise.equipment.property.mapper.class_.brand
            ),
            selectinload(WorkoutRoutine.papers),
        )
    )
    routine = result.scalar_one_or_none()
    if not routine:
        raise NotFoundError("해당 루틴을 찾을 수 없습니다.")
    if routine.user_id != user_id:
        raise ForbiddenError("해당 루틴에 접근할 권한이 없습니다.")
    return routine


async def rename_routine(
    db: AsyncSession,
    routine_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
) -> WorkoutRoutine:
    result = await db.execute(
        select(WorkoutRoutine).where(WorkoutRoutine.id == routine_id, WorkoutRoutine.deleted_at.is_(None))
    )
    routine = result.scalar_one_or_none()
    if not routine:
        raise NotFoundError("해당 루틴을 찾을 수 없습니다.")
    if routine.user_id != user_id:
        raise ForbiddenError("해당 루틴에 접근할 권한이 없습니다.")
    routine.name = name
    await db.commit()
    await db.refresh(routine)
    return routine


async def replace_exercise(
    db: AsyncSession,
    routine_id: uuid.UUID,
    exercise_id: uuid.UUID,
    user_id: uuid.UUID,
    new_exercise_id: uuid.UUID,
) -> RoutineExercise:
    from app.models.exercise import Exercise

    # 루틴 소유자 확인
    routine_result = await db.execute(
        select(WorkoutRoutine).where(WorkoutRoutine.id == routine_id, WorkoutRoutine.deleted_at.is_(None))
    )
    routine = routine_result.scalar_one_or_none()
    if not routine:
        raise NotFoundError("해당 루틴을 찾을 수 없습니다.")
    if routine.user_id != user_id:
        raise ForbiddenError("해당 루틴에 접근할 권한이 없습니다.")

    # 교체할 종목 조회
    re_result = await db.execute(
        select(RoutineExercise)
        .where(RoutineExercise.id == exercise_id)
        .options(selectinload(RoutineExercise.exercise), selectinload(RoutineExercise.equipment))
    )
    routine_exercise = re_result.scalar_one_or_none()
    if not routine_exercise:
        raise NotFoundError("해당 종목을 찾을 수 없습니다.")

    # 새 운동 존재 확인
    new_ex_result = await db.execute(select(Exercise).where(Exercise.id == new_exercise_id))
    new_exercise = new_ex_result.scalar_one_or_none()
    if not new_exercise:
        raise NotFoundError("교체할 종목을 찾을 수 없습니다.")

    routine_exercise.exercise_id = new_exercise_id
    await db.commit()
    await db.refresh(routine_exercise)

    # 새 운동 정보 포함해서 반환
    re_result2 = await db.execute(
        select(RoutineExercise)
        .where(RoutineExercise.id == exercise_id)
        .options(
            selectinload(RoutineExercise.exercise),
            selectinload(RoutineExercise.equipment).selectinload(
                RoutineExercise.equipment.property.mapper.class_.brand
            ),
        )
    )
    return re_result2.scalar_one()


async def delete_routine(
    db: AsyncSession,
    routine_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkoutRoutine:
    result = await db.execute(
        select(WorkoutRoutine).where(WorkoutRoutine.id == routine_id, WorkoutRoutine.deleted_at.is_(None))
    )
    routine = result.scalar_one_or_none()
    if not routine:
        raise NotFoundError("해당 루틴을 찾을 수 없습니다.")
    if routine.user_id != user_id:
        raise ForbiddenError("해당 루틴에 접근할 권한이 없습니다.")
    routine.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(routine)
    return routine


async def get_exercise_paper(
    db: AsyncSession,
    routine_id: uuid.UUID,
    exercise_id: uuid.UUID,
    user_id: uuid.UUID,
) -> RoutinePaper:
    from app.models.chat import Paper

    # 루틴 소유자 확인
    routine_result = await db.execute(
        select(WorkoutRoutine).where(WorkoutRoutine.id == routine_id, WorkoutRoutine.deleted_at.is_(None))
    )
    routine = routine_result.scalar_one_or_none()
    if not routine:
        raise NotFoundError("해당 루틴을 찾을 수 없습니다.")
    if routine.user_id != user_id:
        raise ForbiddenError("해당 루틴에 접근할 권한이 없습니다.")

    result = await db.execute(
        select(RoutinePaper)
        .where(RoutinePaper.routine_id == routine_id, RoutinePaper.routine_exercise_id == exercise_id)
        .options(selectinload(RoutinePaper.paper))
    )
    routine_paper = result.scalar_one_or_none()
    if not routine_paper:
        raise NotFoundError("해당 종목의 논문 근거를 찾을 수 없습니다.")
    return routine_paper
