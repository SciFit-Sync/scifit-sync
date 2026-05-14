"""루틴 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #21-28.

⚠️ POST /routines/generate, /routines/{id}/regenerate 의 RAG 파이프라인은
현재 SSE 스켈레톤만 제공한다. 실제 LLM/ChromaDB 연동은 별도 구현 필요.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models import (
    Equipment,
    EquipmentBrand,
    Exercise,
    Paper,
    RoutineDay,
    RoutineExercise,
    RoutinePaper,
    RoutineStatus,
    User,
    WorkoutRoutine,
)
from app.schemas.common import SuccessResponse
from app.schemas.routines import (
    GenerateRoutineRequest,
    PaperItem,
    RegenerateRoutineRequest,
    ReplacedExerciseData,
    ReplaceRoutineExerciseData,
    ReplaceRoutineExerciseRequest,
    RoutineDayItem,
    RoutineDetail,
    RoutineExerciseItem,
    RoutineExercisePapersData,
    RoutineListData,
    RoutineSummary,
    UpdateRoutineNameRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routines", tags=["routines"])


def _routine_to_summary(r: WorkoutRoutine) -> RoutineSummary:
    return RoutineSummary(
        routine_id=str(r.id),
        name=r.name,
        fitness_goals=r.fitness_goals,
        split_type=r.split_type.value if r.split_type else None,
        generated_by=r.generated_by.value if r.generated_by else "user",
        status=r.status.value if r.status else "active",
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


async def _routine_to_detail(r: WorkoutRoutine, db: AsyncSession) -> RoutineDetail:
    """days + exercises + 운동/장비 이름까지 채워서 detail 반환."""
    days_result = await db.execute(
        select(RoutineDay)
        .where(RoutineDay.routine_id == r.id)
        .options(selectinload(RoutineDay.exercises))
        .order_by(RoutineDay.day_number)
    )
    days = days_result.scalars().unique().all()

    # 운동/장비 이름 prefetch
    ex_ids: list[uuid.UUID] = []
    eq_ids: list[uuid.UUID] = []
    for d in days:
        for ex in d.exercises:
            ex_ids.append(ex.exercise_id)
            if ex.equipment_id:
                eq_ids.append(ex.equipment_id)

    ex_name_map: dict[str, str] = {}
    if ex_ids:
        rows = (await db.execute(select(Exercise.id, Exercise.name).where(Exercise.id.in_(ex_ids)))).all()
        ex_name_map = {str(eid): name for eid, name in rows}

    eq_name_map: dict[str, str] = {}
    if eq_ids:
        rows = (await db.execute(select(Equipment.id, Equipment.name).where(Equipment.id.in_(eq_ids)))).all()
        eq_name_map = {str(eid): name for eid, name in rows}

    # 논문이 연결된 routine_exercise_id 집합
    paper_rows = await db.execute(
        select(RoutinePaper.routine_exercise_id).where(
            RoutinePaper.routine_id == r.id,
            RoutinePaper.routine_exercise_id.isnot(None),
        )
    )
    exercise_ids_with_papers: set[str] = {str(row[0]) for row in paper_rows.all()}

    day_dtos: list[RoutineDayItem] = []
    for d in days:
        ex_dtos = [
            RoutineExerciseItem(
                routine_exercise_id=str(ex.id),
                exercise_id=str(ex.exercise_id),
                exercise_name=ex_name_map.get(str(ex.exercise_id), ""),
                equipment_id=str(ex.equipment_id) if ex.equipment_id else None,
                equipment_name=eq_name_map.get(str(ex.equipment_id)) if ex.equipment_id else None,
                order_index=ex.order_index,
                sets=ex.sets,
                reps_min=ex.reps_min,
                reps_max=ex.reps_max,
                weight_kg=ex.weight_kg,
                rest_seconds=ex.rest_seconds,
                note=ex.note,
                has_paper=str(ex.id) in exercise_ids_with_papers,
            )
            for ex in sorted(d.exercises, key=lambda e: e.order_index)
        ]
        day_dtos.append(
            RoutineDayItem(
                routine_day_id=str(d.id),
                day_number=d.day_number,
                label=d.label,
                exercises=ex_dtos,
            )
        )

    return RoutineDetail(
        routine_id=str(r.id),
        name=r.name,
        fitness_goals=r.fitness_goals,
        split_type=r.split_type.value if r.split_type else None,
        generated_by=r.generated_by.value if r.generated_by else "user",
        status=r.status.value if r.status else "active",
        created_at=r.created_at,
        updated_at=r.updated_at,
        target_muscle_group_ids=r.target_muscle_group_ids,
        session_duration_minutes=r.session_duration_minutes,
        ai_reasoning=r.ai_reasoning,
        days=day_dtos,
    )


def _parse_uuid(v: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise ValidationError(message=f"잘못된 {name} 형식입니다.") from e


async def _get_my_routine(routine_id: str, user: User, db: AsyncSession) -> WorkoutRoutine:
    rid = _parse_uuid(routine_id, "routine_id")
    routine = (
        await db.execute(
            select(WorkoutRoutine).where(
                WorkoutRoutine.id == rid,
                WorkoutRoutine.user_id == user.id,
                WorkoutRoutine.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if routine is None:
        raise NotFoundError(message="루틴을 찾을 수 없습니다.")
    return routine


# ── GET /routines ─────────────────────────────────────────────────────────────
@router.get("", response_model=SuccessResponse[RoutineListData], summary="내 루틴 목록")
async def list_routines(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routines = (
        (
            await db.execute(
                select(WorkoutRoutine)
                .where(WorkoutRoutine.user_id == current_user.id, WorkoutRoutine.deleted_at.is_(None))
                .order_by(WorkoutRoutine.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    items = [_routine_to_summary(r) for r in routines]
    return SuccessResponse(data=RoutineListData(items=items))


# ── GET /routines/{id} ────────────────────────────────────────────────────────
@router.get("/{routine_id}", response_model=SuccessResponse[RoutineDetail], summary="루틴 상세")
async def get_routine(
    routine_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine = await _get_my_routine(routine_id, current_user, db)
    detail = await _routine_to_detail(routine, db)
    return SuccessResponse(data=detail)


# ── PATCH /routines/{id}/name ─────────────────────────────────────────────────
@router.patch("/{routine_id}/name", response_model=SuccessResponse[RoutineSummary], summary="루틴 이름 수정")
async def rename_routine(
    routine_id: str,
    body: UpdateRoutineNameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine = await _get_my_routine(routine_id, current_user, db)
    routine.name = body.name
    await db.commit()
    await db.refresh(routine)
    return SuccessResponse(data=_routine_to_summary(routine))


# ── PATCH /routines/{id}/exercises/{exId} ─────────────────────────────────────
@router.patch(
    "/{routine_id}/exercises/{routine_exercise_id}",
    response_model=SuccessResponse[ReplaceRoutineExerciseData],
    summary="루틴 종목 교체",
)
async def replace_routine_exercise(
    routine_id: str,
    routine_exercise_id: str,
    body: ReplaceRoutineExerciseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_my_routine(routine_id, current_user, db)
    rex_id = _parse_uuid(routine_exercise_id, "routine_exercise_id")
    rex = (await db.execute(select(RoutineExercise).where(RoutineExercise.id == rex_id))).scalar_one_or_none()
    if rex is None:
        raise NotFoundError(message="루틴 내 운동을 찾을 수 없습니다.")

    # 종목 교체 처리
    if body.new_exercise_id is not None:
        new_ex_id = _parse_uuid(body.new_exercise_id, "new_exercise_id")
        new_ex = (await db.execute(select(Exercise).where(Exercise.id == new_ex_id))).scalar_one_or_none()
        if new_ex is None:
            raise NotFoundError(message="교체할 운동을 찾을 수 없습니다.")
        rex.exercise_id = new_ex_id
        rex.equipment_id = None  # 새 종목에 맞는 기구는 초기화
        await db.commit()
        await db.refresh(rex)
        return SuccessResponse(
            data=RoutineExerciseItem(
                routine_exercise_id=str(rex.id),
                exercise_id=str(rex.exercise_id),
                exercise_name=new_ex.name,
                equipment_id=None,
                equipment_name=None,
                order_index=rex.order_index,
                sets=rex.sets,
                reps_min=rex.reps_min,
                reps_max=rex.reps_max,
                weight_kg=rex.weight_kg,
                rest_seconds=rex.rest_seconds,
                note=rex.note,
            )
        )

    # 세부 정보 수정 처리
    update_fields = body.model_dump(exclude_unset=True, exclude={"new_exercise_id"})
    for field, value in update_fields.items():
        setattr(rex, field, value)
    await db.commit()
    await db.refresh(rex)

    # 장비 이름 및 브랜드 조회
    equipment_name: str | None = None
    brand_name: str | None = None
    if rex.equipment_id:
        eq_row = (
            await db.execute(
                select(Equipment.name, EquipmentBrand.name)
                .outerjoin(EquipmentBrand, Equipment.brand_id == EquipmentBrand.id)
                .where(Equipment.id == rex.equipment_id)
            )
        ).one_or_none()
        if eq_row:
            equipment_name, brand_name = eq_row

    return SuccessResponse(
        data=ReplaceRoutineExerciseData(
            message="종목이 교체되었습니다.",
            new_exercise=ReplacedExerciseData(
                exercise_id=str(new_exercise.id),
                name=new_exercise.name,
                equipment=equipment_name,
                brand=brand_name,
                sets=rex.sets,
                reps_min=rex.reps_min,
                reps_max=rex.reps_max,
            ),
        )
    )


# ── DELETE /routines/{id} ─────────────────────────────────────────────────────
@router.delete("/{routine_id}", response_model=SuccessResponse[None], summary="루틴 삭제 (soft delete)")
async def delete_routine(
    routine_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine = await _get_my_routine(routine_id, current_user, db)
    routine.deleted_at = datetime.now(timezone.utc)
    routine.status = RoutineStatus.ARCHIVED
    await db.commit()
    return SuccessResponse(data=None)


# ── GET /routines/{id}/exercises/{exId}/paper ─────────────────────────────────
@router.get(
    "/{routine_id}/exercises/{routine_exercise_id}/paper",
    response_model=SuccessResponse[RoutineExercisePapersData],
    summary="루틴 운동 근거 논문",
)
async def get_routine_exercise_papers(
    routine_id: str,
    routine_exercise_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_my_routine(routine_id, current_user, db)
    rex_id = _parse_uuid(routine_exercise_id, "routine_exercise_id")

    rows = (
        await db.execute(
            select(RoutinePaper, Paper)
            .join(Paper, RoutinePaper.paper_id == Paper.id)
            .where(RoutinePaper.routine_exercise_id == rex_id)
        )
    ).all()
    items = [
        PaperItem(
            paper_id=str(p.id),
            title=p.title,
            authors=p.authors,
            journal=p.journal,
            year=p.year,
            doi=p.doi,
            pmid=p.pmid,
            relevance_summary=rp.relevance_summary,
        )
        for rp, p in rows
    ]
    return SuccessResponse(data=RoutineExercisePapersData(routine_exercise_id=routine_exercise_id, items=items))


# ── POST /routines/generate (SSE) ─────────────────────────────────────────────
async def _generate_routine_stream(_user: User, body: GenerateRoutineRequest):
    """⚠️ TODO: 실제 RAG 파이프라인 (한→영 번역 → 임베딩 → ChromaDB 검색 → LLM 스트리밍).
    현재는 SSE 포맷만 시연하는 스텁. CLAUDE.md §6 RAG 파이프라인 참고.
    """
    yield f"id: evt_001\ndata: {json.dumps({'type': 'started', 'goals': body.goals})}\n\n"
    await asyncio.sleep(0)
    yield (f"id: evt_002\ndata: {json.dumps({'type': 'message', 'content': 'RAG 파이프라인 미구현 — TODO'})}\n\n")
    yield "data: [DONE]\n\n"


@router.post("/generate", summary="AI 루틴 생성 (SSE)")
async def generate_routine(
    body: GenerateRoutineRequest,
    current_user: User = Depends(get_current_user),
):
    return StreamingResponse(
        _generate_routine_stream(current_user, body),
        media_type="text/event-stream",
    )


# ── POST /routines/{id}/regenerate ────────────────────────────────────────────
@router.post("/{routine_id}/regenerate", summary="루틴 재생성 (SSE)")
async def regenerate_routine(
    routine_id: str,
    body: RegenerateRoutineRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_my_routine(routine_id, current_user, db)

    async def stream():
        yield (f"id: evt_001\ndata: {json.dumps({'type': 'started', 'feedback': body.feedback or ''})}\n\n")
        await asyncio.sleep(0)
        yield (f"id: evt_002\ndata: {json.dumps({'type': 'message', 'content': 'RAG 재생성 미구현 — TODO'})}\n\n")
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
