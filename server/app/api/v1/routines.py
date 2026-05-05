import logging
import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.routine import (
    DeleteRoutineData,
    GenerateRoutineRequest,
    NewExerciseData,
    PaperData,
    RenameRoutineData,
    RenameRoutineRequest,
    ReplaceExerciseData,
    ReplaceExerciseRequest,
    RoutineDetail,
    RoutineDayDetail,
    ExerciseDetail,
    RoutineListData,
    RoutineSummary,
)
from app.services import routine as routine_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routines", tags=["routines"])


# ── 1. 루틴 생성 (SSE) ────────────────────────────────────────────────────────

@router.post("/generate", summary="AI 루틴 생성 (SSE)")
async def generate_routine(
    body: GenerateRoutineRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    async def event_stream():
        yield 'data: {"type": "chunk", "content": "루틴을 생성하는 중입니다..."}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── 2. 루틴 목록 조회 ─────────────────────────────────────────────────────────

@router.get("", response_model=SuccessResponse[RoutineListData], summary="루틴 목록 조회")
async def list_routines(
    goal: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    size: int = Query(default=10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routines, total = await routine_svc.list_routines(db, current_user.id, goal, page, size)

    summaries = []
    for r in routines:
        days_per_week = len(r.days)
        paper_count = len(r.papers)
        # targetMuscles는 현재 모델에 별도 컬럼 없으므로 빈 리스트
        summaries.append(
            RoutineSummary(
                routineId=str(r.id),
                name=r.name,
                goal=r.fitness_goal,
                targetMuscles=[],
                daysPerWeek=days_per_week,
                sessionMinutes=0,
                paperCount=paper_count,
                createdAt=r.created_at.strftime("%Y-%m-%d"),
            )
        )

    return SuccessResponse(data=RoutineListData(routines=summaries, totalCount=total))


# ── 3. 루틴 상세 조회 ─────────────────────────────────────────────────────────

@router.get("/{routine_id}", response_model=SuccessResponse[RoutineDetail], summary="루틴 상세 조회")
async def get_routine(
    routine_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine = await routine_svc.get_routine_detail(db, routine_id, current_user.id)

    paper_exercise_ids = {str(p.routine_exercise_id) for p in routine.papers if p.routine_exercise_id}

    days = []
    for day in sorted(routine.days, key=lambda d: d.day_number):
        exercises = []
        for ex in sorted(day.exercises, key=lambda e: e.order_index):
            eq = ex.equipment
            exercises.append(
                ExerciseDetail(
                    exerciseId=str(ex.id),
                    name=ex.exercise.name if ex.exercise else "",
                    equipment=eq.name if eq else None,
                    brand=eq.brand.name if eq and eq.brand else None,
                    sets=ex.sets,
                    repsMin=ex.reps,
                    repsMax=ex.reps,
                    weightKg=ex.weight_kg,
                    hasPaper=str(ex.id) in paper_exercise_ids,
                )
            )
        days.append(
            RoutineDayDetail(
                dayNumber=day.day_number,
                label=day.name,
                totalMinutes=0,
                exercises=exercises,
            )
        )

    return SuccessResponse(
        data=RoutineDetail(routineId=str(routine.id), name=routine.name, days=days)
    )


# ── 4. 루틴 이름 수정 ─────────────────────────────────────────────────────────

@router.patch("/{routine_id}/name", response_model=SuccessResponse[RenameRoutineData], summary="루틴 이름 수정")
async def rename_routine(
    routine_id: uuid.UUID,
    body: RenameRoutineRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine = await routine_svc.rename_routine(db, routine_id, current_user.id, body.name)
    return SuccessResponse(data=RenameRoutineData(routineId=str(routine.id), name=routine.name))


# ── 5. 루틴 종목 교체 ─────────────────────────────────────────────────────────

@router.patch(
    "/{routine_id}/exercises/{exercise_id}",
    response_model=SuccessResponse[ReplaceExerciseData],
    summary="루틴 종목 교체",
)
async def replace_exercise(
    routine_id: uuid.UUID,
    exercise_id: uuid.UUID,
    body: ReplaceExerciseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine_exercise = await routine_svc.replace_exercise(
        db, routine_id, exercise_id, current_user.id, body.newExerciseId
    )
    eq = routine_exercise.equipment
    return SuccessResponse(
        data=ReplaceExerciseData(
            message="종목이 교체되었습니다.",
            newExercise=NewExerciseData(
                exerciseId=str(routine_exercise.exercise_id),
                name=routine_exercise.exercise.name if routine_exercise.exercise else "",
                equipment=eq.name if eq else None,
                brand=eq.brand.name if eq and eq.brand else None,
                sets=routine_exercise.sets,
                repsMin=routine_exercise.reps,
                repsMax=routine_exercise.reps,
            ),
        )
    )


# ── 6. 루틴 재생성 (SSE) ──────────────────────────────────────────────────────

@router.post("/{routine_id}/regenerate", summary="루틴 재생성 (SSE)")
async def regenerate_routine(
    routine_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    async def event_stream():
        yield 'data: {"type": "chunk", "content": "루틴을 재생성하는 중입니다..."}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── 7. 루틴 삭제 ──────────────────────────────────────────────────────────────

@router.delete("/{routine_id}", response_model=SuccessResponse[DeleteRoutineData], summary="루틴 삭제")
async def delete_routine(
    routine_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine = await routine_svc.delete_routine(db, routine_id, current_user.id)
    return SuccessResponse(
        data=DeleteRoutineData(
            routineId=str(routine.id),
            deletedAt=routine.deleted_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        )
    )


# ── 8. 논문 근거 조회 ─────────────────────────────────────────────────────────

@router.get(
    "/{routine_id}/exercises/{exercise_id}/paper",
    response_model=SuccessResponse[PaperData],
    summary="종목 논문 근거 조회",
)
async def get_exercise_paper(
    routine_id: uuid.UUID,
    exercise_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine_paper = await routine_svc.get_exercise_paper(db, routine_id, exercise_id, current_user.id)
    paper = routine_paper.paper
    return SuccessResponse(
        data=PaperData(
            paperId=str(paper.id),
            title=paper.title,
            authors=paper.authors,
            journal=paper.journal,
            publishedYear=paper.published_year,
            doi=paper.doi,
            abstract=paper.abstract,
            relevanceSummary=routine_paper.relevance_summary,
        )
    )
