"""루틴 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #21-28.

POST /routines/generate, /routines/{id}/regenerate 는 services/rag.routine_rag_stream
을 호출하여 LLM 토큰 → SSE chunk 이벤트로 전달하고, 파싱된 day별 결과를
load_calc 기반 weight_kg 계산과 함께 DB에 저장한다 (CLAUDE.md §11 RAG 파이프라인).
"""

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_required_profile
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.limiter import rate_limit
from app.models import (
    Equipment,
    EquipmentBrand,
    Exercise,
    ExerciseEquipmentMap,
    ExerciseMuscle,
    Gym,
    MuscleGroup,
    Paper,
    RoutineDay,
    RoutineExercise,
    RoutinePaper,
    RoutineStatus,
    User,
    UserBodyMeasurement,
    UserExercise1RM,
    WorkoutRoutine,
)
from app.models import (
    UserProfile as DBUserProfile,
)
from app.models.gym import GymEquipment
from app.models.routine import GeneratedBy, SplitType
from app.schemas.common import SuccessResponse
from app.schemas.routines import (
    GenerateRoutineRequest,
    GymSummary,
    MuscleActivationItem,
    PaperItem,
    RegenerateRoutineRequest,
    ReplacedExerciseData,
    ReplaceRoutineExerciseData,
    RoutineDayItem,
    RoutineDeleteData,
    RoutineDetail,
    RoutineExerciseItem,
    RoutineExercisePapersData,
    RoutineListData,
    RoutineSummary,
    UpdateRoutineExerciseRequest,
    UpdateRoutineNameRequest,
)
from app.services.rag import UserProfile as RagUserProfile
from app.services.rag import routine_rag_stream
from app.services.routine_targets import derive_exercise_targets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routines", tags=["routines"])


def _routine_to_summary(r: WorkoutRoutine, gym_name: str | None = None) -> RoutineSummary:
    return RoutineSummary(
        routine_id=str(r.id),
        name=r.name,
        fitness_goals=r.fitness_goals,
        split_type=r.split_type.value if r.split_type else None,
        generated_by=r.generated_by.value if r.generated_by else "user",
        status=r.status.value if r.status else "active",
        gym_id=str(r.gym_id) if r.gym_id else None,
        gym_name=gym_name,
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
    eq_brand_map: dict[str, str] = {}
    if eq_ids:
        rows = (
            await db.execute(
                select(Equipment.id, Equipment.name, EquipmentBrand.name)
                .outerjoin(EquipmentBrand, EquipmentBrand.id == Equipment.brand_id)
                .where(Equipment.id.in_(eq_ids))
            )
        ).all()
        for eid, eq_name, brand_name in rows:
            eq_name_map[str(eid)] = eq_name
            if brand_name:
                eq_brand_map[str(eid)] = brand_name

    # 근육 활성화 비율 prefetch
    muscle_activation_map: dict[str, list[MuscleActivationItem]] = {}
    if ex_ids:
        ma_rows = (
            await db.execute(
                select(ExerciseMuscle.exercise_id, MuscleGroup.name_ko, ExerciseMuscle.activation_pct)
                .join(MuscleGroup, MuscleGroup.id == ExerciseMuscle.muscle_group_id)
                .where(ExerciseMuscle.exercise_id.in_(ex_ids))
            )
        ).all()
        for eid, name_ko, pct in ma_rows:
            muscle_activation_map.setdefault(str(eid), []).append(
                MuscleActivationItem(muscle=name_ko, activation_pct=pct)
            )

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
        sorted_exs = sorted(d.exercises, key=lambda e: e.order_index)
        ex_dtos = [
            RoutineExerciseItem(
                routine_exercise_id=str(ex.id),
                exercise_id=str(ex.exercise_id),
                exercise_name=ex_name_map.get(str(ex.exercise_id), ""),
                equipment_id=str(ex.equipment_id) if ex.equipment_id else None,
                equipment_name=eq_name_map.get(str(ex.equipment_id)) if ex.equipment_id else None,
                brand=eq_brand_map.get(str(ex.equipment_id)) if ex.equipment_id else None,
                order_index=ex.order_index,
                sets=ex.sets,
                reps_min=ex.reps_min,
                reps_max=ex.reps_max,
                weight_kg=ex.weight_kg,
                rest_seconds=ex.rest_seconds,
                note=ex.note,
                has_paper=str(ex.id) in exercise_ids_with_papers,
                has_tips=False,
                muscle_activation=muscle_activation_map.get(str(ex.exercise_id), []),
            )
            for ex in sorted_exs
        ]
        total_secs = sum(ex.sets * (45 + ex.rest_seconds) for ex in sorted_exs) if sorted_exs else None
        day_dtos.append(
            RoutineDayItem(
                routine_day_id=str(d.id),
                day_number=d.day_number,
                label=d.label,
                total_minutes=max(1, round(total_secs / 60)) if total_secs else None,
                exercises=ex_dtos,
            )
        )

    # gym 정보
    gym_summary: GymSummary | None = None
    if r.gym_id:
        gym_row = (await db.execute(select(Gym).where(Gym.id == r.gym_id))).scalar_one_or_none()
        if gym_row:
            gym_summary = GymSummary(gym_id=str(gym_row.id), name=gym_row.name)

    return RoutineDetail(
        routine_id=str(r.id),
        name=r.name,
        fitness_goals=r.fitness_goals,
        split_type=r.split_type.value if r.split_type else None,
        generated_by=r.generated_by.value if r.generated_by else "user",
        status=r.status.value if r.status else "active",
        gym_id=str(r.gym_id) if r.gym_id else None,
        gym_name=gym_summary.name if gym_summary else None,
        gym=gym_summary,
        created_at=r.created_at,
        updated_at=r.updated_at,
        target_muscle_group_ids=r.target_muscle_group_ids,
        session_minutes=r.session_minutes,
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
    gym_id: str | None = Query(None, description="gym_id 필터 — 해당 헬스장의 루틴만 반환"),
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    gym_uuid: uuid.UUID | None = None
    if gym_id:
        try:
            gym_uuid = uuid.UUID(gym_id)
        except ValueError as e:
            raise ValidationError(message="잘못된 gym_id 형식입니다.") from e

    stmt = (
        select(WorkoutRoutine, Gym.name)
        .outerjoin(Gym, WorkoutRoutine.gym_id == Gym.id)
        .where(WorkoutRoutine.user_id == current_user.id, WorkoutRoutine.deleted_at.is_(None))
    )
    if gym_uuid:
        stmt = stmt.where(WorkoutRoutine.gym_id == gym_uuid)
    stmt = stmt.order_by(WorkoutRoutine.updated_at.desc())

    rows = (await db.execute(stmt)).all()
    items = [_routine_to_summary(r, gym_name) for r, gym_name in rows]
    return SuccessResponse(data=RoutineListData(items=items))


# ── GET /routines/{id} ────────────────────────────────────────────────────────
@router.get("/{routine_id}", response_model=SuccessResponse[RoutineDetail], summary="루틴 상세")
async def get_routine(
    routine_id: str,
    current_user: User = Depends(get_required_profile),
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
    current_user: User = Depends(get_required_profile),
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
    body: UpdateRoutineExerciseRequest,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    routine = await _get_my_routine(routine_id, current_user, db)
    rex_id = _parse_uuid(routine_exercise_id, "routine_exercise_id")
    rex = (await db.execute(select(RoutineExercise).where(RoutineExercise.id == rex_id))).scalar_one_or_none()
    if rex is None:
        raise NotFoundError(message="루틴 내 운동을 찾을 수 없습니다.")

    new_ex = None
    if body.new_exercise_id is not None:
        new_ex_id = _parse_uuid(body.new_exercise_id, "new_exercise_id")
        new_ex = (await db.execute(select(Exercise).where(Exercise.id == new_ex_id))).scalar_one_or_none()
        if new_ex is None:
            raise NotFoundError(message="교체할 운동을 찾을 수 없습니다.")

        # D-M9: 루틴에 gym_id가 있으면, 교체 운동과 연결된 equipment가 해당 gym 소속인지 검증
        if routine.gym_id:
            gym_eq_ids = {
                row[0]
                for row in (
                    await db.execute(select(GymEquipment.equipment_id).where(GymEquipment.gym_id == routine.gym_id))
                ).all()
            }
            ex_eq_ids = {
                row[0]
                for row in (
                    await db.execute(
                        select(ExerciseEquipmentMap.equipment_id).where(ExerciseEquipmentMap.exercise_id == new_ex_id)
                    )
                ).all()
            }
            if ex_eq_ids and not ex_eq_ids.intersection(gym_eq_ids):
                raise ValidationError(message="교체할 운동의 기구가 해당 루틴의 헬스장에 없습니다.")

        rex.exercise_id = new_ex_id
        rex.equipment_id = None

    if body.sets is not None:
        rex.sets = body.sets
    if body.reps_min is not None:
        rex.reps_min = body.reps_min
    if body.reps_max is not None:
        rex.reps_max = body.reps_max
    if body.weight_kg is not None:
        rex.weight_kg = body.weight_kg
    if body.rest_seconds is not None:
        rex.rest_seconds = body.rest_seconds
    if body.note is not None:
        rex.note = body.note

    await db.commit()
    await db.refresh(rex)

    target_ex = (
        new_ex or (await db.execute(select(Exercise).where(Exercise.id == rex.exercise_id))).scalar_one_or_none()
    )
    return SuccessResponse(
        data=ReplaceRoutineExerciseData(
            message="종목이 업데이트되었습니다.",
            new_exercise=ReplacedExerciseData(
                exercise_id=str(target_ex.id),
                name=target_ex.name,
                equipment=None,
                brand=None,
                sets=rex.sets,
                reps_min=rex.reps_min,
                reps_max=rex.reps_max,
            ),
        )
    )


# ── DELETE /routines/{id} ─────────────────────────────────────────────────────
@router.delete("/{routine_id}", response_model=SuccessResponse[RoutineDeleteData], summary="루틴 삭제 (soft delete)")
async def delete_routine(
    routine_id: str,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    routine = await _get_my_routine(routine_id, current_user, db)
    routine.deleted_at = datetime.utcnow()
    routine.status = RoutineStatus.ARCHIVED
    await db.commit()
    return SuccessResponse(
        data=RoutineDeleteData(
            routine_id=str(routine.id),
            deleted_at=routine.deleted_at,
        )
    )


# ── GET /routines/{id}/exercises/{exId}/paper ─────────────────────────────────
@router.get(
    "/{routine_id}/exercises/{routine_exercise_id}/paper",
    response_model=SuccessResponse[RoutineExercisePapersData],
    summary="루틴 운동 근거 논문",
)
async def get_routine_exercise_papers(
    routine_id: str,
    routine_exercise_id: str,
    current_user: User = Depends(get_required_profile),
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
            year=p.published_year,
            doi=p.doi,
            pmid=p.pmid,
            relevance_summary=rp.relevance_summary,
        )
        for rp, p in rows
    ]
    return SuccessResponse(data=RoutineExercisePapersData(routine_exercise_id=routine_exercise_id, items=items))


# ── RAG/SSE 공통 헬퍼 ─────────────────────────────────────────────────────────

_SPLIT_TO_DAYS: dict[SplitType, int] = {
    SplitType.TWO: 2,
    SplitType.THREE: 3,
    SplitType.FOUR: 4,
    SplitType.FIVE: 5,
}


def _sse(seq: int, payload: dict) -> str:
    """SSE 한 이벤트 직렬화. 한국어가 그대로 흘러갈 수 있도록 ensure_ascii=False."""
    return f"id: evt_{seq:03d}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_done() -> str:
    """SSE 종료 마커. CLAUDE.md §7 명세."""
    return "data: [DONE]\n\n"


async def _async_iter_sync_gen(make_gen):
    """블로킹 sync generator를 백그라운드 스레드에서 돌리고 async iterator로 노출.

    LLM 토큰 스트리밍(`generate_content_stream`)이 동기 함수이므로
    이벤트 루프를 막지 않도록 별도 스레드로 격리한다.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    sentinel = object()

    def producer():
        try:
            for item in make_gen():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as e:  # noqa: BLE001 - LLM/ChromaDB 어떤 오류든 SSE error로 통보
            logger.exception("RAG 생성 중 예외")
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": f"RAG 파이프라인 오류: {e}"},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=producer, daemon=True).start()

    while True:
        item = await queue.get()
        if item is sentinel:
            return
        yield item


async def _build_rag_profile(
    user: User,
    body: GenerateRoutineRequest | RegenerateRoutineRequest,
    db: AsyncSession,
    *,
    feedback: str | None = None,
    overrides: GenerateRoutineRequest | None = None,
) -> RagUserProfile:
    """User + UserProfile + 최신 BodyMeasurement + gym_equipments를 모아 RAG 프로필 구성."""
    # 1. UserProfile (필수)
    profile = (await db.execute(select(DBUserProfile).where(DBUserProfile.user_id == user.id))).scalar_one_or_none()
    if profile is None:
        raise ValidationError(message="신체 프로필 정보가 없습니다. 회원가입 신체정보 입력을 완료해 주세요.")

    # 2. 최신 체중 (UserBodyMeasurement)
    body_row = (
        await db.execute(
            select(UserBodyMeasurement)
            .where(UserBodyMeasurement.user_id == user.id)
            .order_by(UserBodyMeasurement.measured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    body_weight = float(body_row.weight_kg) if body_row else 70.0  # fallback (성인 평균)

    # 3. days_per_week ← split_type
    req: GenerateRoutineRequest | None = overrides or (body if isinstance(body, GenerateRoutineRequest) else None)
    days_per_week = 3
    if req and req.split_type:
        try:
            days_per_week = _SPLIT_TO_DAYS.get(SplitType(req.split_type), 3)
        except ValueError:
            days_per_week = 3

    # 4. gym_equipments → equipment_type 리스트
    available_equipment: list[str] = []
    gym_id_str = req.gym_id if req else None
    if gym_id_str:
        try:
            gid = uuid.UUID(gym_id_str)
            rows = (
                await db.execute(
                    select(Equipment.equipment_type)
                    .join(GymEquipment, GymEquipment.equipment_id == Equipment.id)
                    .where(GymEquipment.gym_id == gid)
                    .distinct()
                )
            ).all()
            available_equipment = sorted({et.value if hasattr(et, "value") else str(et) for (et,) in rows})
        except ValueError:
            logger.warning("gym_id가 UUID가 아님: %s", gym_id_str)

    return RagUserProfile(
        goals=(req.goals if req else []),
        body_weight=body_weight,
        fitness_career=profile.career_level.value,
        days_per_week=days_per_week,
        available_equipment=available_equipment,
        target_muscles=(req.target_muscle_group_ids if req else []) or [],
        session_minutes=(req.session_minutes if req else None),
        injury=(req.injury if req else None),
        feedback=feedback,
    )


async def _resolve_exercise_id(name: str, db: AsyncSession) -> uuid.UUID | None:
    """LLM이 출력한 운동 이름 → exercises.id. name_en/name 모두 시도, 없으면 None."""
    if not name or not name.strip():
        return None
    name_lc = name.strip().lower()

    # 1) name_en 정확 매치 (lower)
    from sqlalchemy import func as sa_func

    row = (
        await db.execute(select(Exercise.id).where(sa_func.lower(Exercise.name_en) == name_lc).limit(1))
    ).scalar_one_or_none()
    if row is not None:
        return row

    # 2) name (한글) 정확 매치
    row = (await db.execute(select(Exercise.id).where(Exercise.name == name.strip()).limit(1))).scalar_one_or_none()
    if row is not None:
        return row

    # 3) name_en ILIKE %name% (부분 매치)
    row = (
        await db.execute(select(Exercise.id).where(Exercise.name_en.ilike(f"%{name.strip()}%")).limit(1))
    ).scalar_one_or_none()
    return row


async def _fetch_user_1rms(user_id: uuid.UUID, db: AsyncSession) -> dict[uuid.UUID, float]:
    """사용자의 운동별 1RM 매핑. exercise_id → weight_kg."""
    rows = (
        await db.execute(
            select(UserExercise1RM.exercise_id, UserExercise1RM.weight_kg).where(UserExercise1RM.user_id == user_id)
        )
    ).all()
    return {ex_id: float(w) for ex_id, w in rows}


async def _persist_day(
    *,
    routine_id: uuid.UUID,
    day_data: dict,
    primary_goal: str,
    user_1rms: dict[uuid.UUID, float],
    db: AsyncSession,
) -> tuple[RoutineDay, list[RoutineExercise], list[uuid.UUID]]:
    """LLM이 보낸 day_complete 이벤트를 RoutineDay + RoutineExercise[] 로 저장.

    Returns:
        (day, exercises, dropped_exercise_indices) — 매칭 실패해 제외된 LLM 운동 위치.
    """
    day_number = int(day_data.get("day") or 1)
    label = str(day_data.get("focus") or f"Day {day_number}")[:200]

    day = RoutineDay(routine_id=routine_id, day_number=day_number, label=label)
    db.add(day)
    await db.flush()  # day.id 확보

    exercises: list[RoutineExercise] = []
    llm_exercises = day_data.get("exercises") or []
    for idx, ex_data in enumerate(llm_exercises):
        if not isinstance(ex_data, dict):
            continue
        name = str(ex_data.get("name") or "").strip()
        exercise_id = await _resolve_exercise_id(name, db)
        if exercise_id is None:
            logger.warning("운동 '%s' 매칭 실패 — 제외", name)
            continue

        targets = derive_exercise_targets(
            goal=primary_goal,
            user_1rm_kg=user_1rms.get(exercise_id),
            llm_sets=ex_data.get("sets"),
            llm_reps_min=ex_data.get("reps_min"),
            llm_reps_max=ex_data.get("reps_max"),
            llm_rest_seconds=ex_data.get("rest_seconds"),
        )

        rex = RoutineExercise(
            routine_day_id=day.id,
            exercise_id=exercise_id,
            order_index=idx,
            sets=targets["sets"],
            reps_min=targets["reps_min"],
            reps_max=targets["reps_max"],
            weight_kg=targets["weight_kg"],
            rest_seconds=targets["rest_seconds"],
            note=(ex_data.get("notes") or None),
        )
        db.add(rex)
        exercises.append(rex)

    await db.flush()
    return day, exercises, []


async def _persist_papers(
    *,
    routine_id: uuid.UUID,
    sources: list[dict],
    db: AsyncSession,
) -> int:
    """sources 의 pmid를 papers.id로 변환하여 RoutinePaper를 일괄 insert. 저장 개수 반환."""
    pmids = [s.get("pmid") for s in sources if s.get("pmid")]
    if not pmids:
        return 0

    rows = (await db.execute(select(Paper.id, Paper.pmid).where(Paper.pmid.in_(pmids)))).all()
    pmid_to_id: dict[str, uuid.UUID] = {pmid: pid for pid, pmid in rows}

    inserted = 0
    for src in sources:
        pmid = src.get("pmid")
        paper_id = pmid_to_id.get(pmid)
        if paper_id is None:
            continue
        db.add(
            RoutinePaper(
                routine_id=routine_id,
                paper_id=paper_id,
                relevance_summary=src.get("section") or None,
            )
        )
        inserted += 1
    if inserted:
        await db.flush()
    return inserted


async def _run_rag_to_sse(
    *,
    user: User,
    routine: WorkoutRoutine,
    profile: RagUserProfile,
    db: AsyncSession,
    initial_event: dict,
) -> AsyncIterator[str]:
    """공통 SSE 스트림: started → chunk*/day_complete*/papers → done → [DONE]."""
    seq = 1
    yield _sse(seq, initial_event)

    primary_goal = profile.primary_goal
    user_1rms = await _fetch_user_1rms(user.id, db)

    error_emitted = False
    try:
        async for ev in _async_iter_sync_gen(lambda: routine_rag_stream(profile)):
            etype = ev.get("type")
            seq += 1

            if etype == "chunk":
                # 1초당 다수 토큰이 흐름. content는 그대로 노출.
                yield _sse(seq, {"type": "chunk", "content": ev.get("content", "")})

            elif etype == "day_complete":
                day, rexes, _dropped = await _persist_day(
                    routine_id=routine.id,
                    day_data=ev,
                    primary_goal=primary_goal,
                    user_1rms=user_1rms,
                    db=db,
                )
                yield _sse(
                    seq,
                    {
                        "type": "day_complete",
                        "day": day.day_number,
                        "data": {
                            "routine_day_id": str(day.id),
                            "day_number": day.day_number,
                            "label": day.label,
                            "exercises": [
                                {
                                    "routine_exercise_id": str(rex.id),
                                    "exercise_id": str(rex.exercise_id),
                                    "order_index": rex.order_index,
                                    "sets": rex.sets,
                                    "reps_min": rex.reps_min,
                                    "reps_max": rex.reps_max,
                                    "weight_kg": rex.weight_kg,
                                    "rest_seconds": rex.rest_seconds,
                                    "note": rex.note,
                                }
                                for rex in rexes
                            ],
                        },
                    },
                )

            elif etype == "papers":
                inserted = await _persist_papers(
                    routine_id=routine.id,
                    sources=ev.get("sources") or [],
                    db=db,
                )
                yield _sse(
                    seq,
                    {
                        "type": "papers",
                        "count": inserted,
                        "sources": ev.get("sources") or [],
                    },
                )

            elif etype == "error":
                error_emitted = True
                yield _sse(seq, {"type": "error", "message": ev.get("message", "오류")})

            elif etype == "done":
                # routine_rag_stream 내부의 done은 무시 — 라우터가 최종 done을 emit
                pass
            else:
                logger.debug("알 수 없는 RAG 이벤트 타입: %s", etype)

        # 모든 day_complete 후 commit. 중간 flush들은 트랜잭션 안에서 유지.
        if not error_emitted:
            await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("SSE 스트림 중 예외")
        await db.rollback()
        seq += 1
        yield _sse(seq, {"type": "error", "message": f"내부 오류: {e}"})

    seq += 1
    yield _sse(seq, {"type": "done", "routine_id": str(routine.id)})
    yield _sse_done()


# ── POST /routines/generate (SSE) ─────────────────────────────────────────────
@router.post("/generate", summary="AI 루틴 생성 (SSE)")
@rate_limit("5/minute")
async def generate_routine(
    request: Request,
    body: GenerateRoutineRequest,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    if not body.goals:
        raise ValidationError(message="goals는 비어 있을 수 없습니다.")

    split = SplitType(body.split_type) if body.split_type else None
    gym_uuid = None
    if body.gym_id:
        try:
            gym_uuid = uuid.UUID(body.gym_id)
        except ValueError as e:
            raise ValidationError(message="gym_id 형식이 올바르지 않습니다.") from e

    routine = WorkoutRoutine(
        user_id=current_user.id,
        gym_id=gym_uuid,
        name=f"AI 루틴 ({', '.join(body.goals)})",
        fitness_goals=[g.lower() for g in body.goals],
        split_type=split,
        target_muscle_group_ids=body.target_muscle_group_ids or [],
        session_minutes=body.session_minutes,
        generated_by=GeneratedBy.AI,
        status=RoutineStatus.ACTIVE,
    )
    db.add(routine)
    await db.commit()
    await db.refresh(routine)

    profile = await _build_rag_profile(current_user, body, db)

    return StreamingResponse(
        _run_rag_to_sse(
            user=current_user,
            routine=routine,
            profile=profile,
            db=db,
            initial_event={
                "type": "started",
                "routine_id": str(routine.id),
                "goals": [g.lower() for g in body.goals],
            },
        ),
        media_type="text/event-stream",
    )


# ── POST /routines/{id}/regenerate ────────────────────────────────────────────
@router.post("/{routine_id}/regenerate", summary="루틴 재생성 (SSE)")
@rate_limit("5/minute")
async def regenerate_routine(
    request: Request,
    routine_id: str,
    body: RegenerateRoutineRequest,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    routine = await _get_my_routine(routine_id, current_user, db)

    # 기존 day/exercise/paper 제거 (cascade로 exercise는 함께 삭제됨)
    existing_days = (await db.execute(select(RoutineDay).where(RoutineDay.routine_id == routine.id))).scalars().all()
    for d in existing_days:
        await db.delete(d)
    existing_papers = (
        (await db.execute(select(RoutinePaper).where(RoutinePaper.routine_id == routine.id))).scalars().all()
    )
    for p in existing_papers:
        await db.delete(p)
    await db.flush()

    # 기존 루틴의 메타데이터로 RAG 프로필 구성 (재생성은 GenerateRoutineRequest 본문이 없음)
    pseudo_req = GenerateRoutineRequest(
        goals=list(routine.fitness_goals or []),
        target_muscle_group_ids=list(routine.target_muscle_group_ids or []),
        session_minutes=routine.session_minutes,
        split_type=routine.split_type.value if routine.split_type else None,
        gym_id=str(routine.gym_id) if routine.gym_id else None,
        injury=None,
    )
    profile = await _build_rag_profile(current_user, body, db, feedback=body.feedback, overrides=pseudo_req)

    return StreamingResponse(
        _run_rag_to_sse(
            user=current_user,
            routine=routine,
            profile=profile,
            db=db,
            initial_event={
                "type": "started",
                "routine_id": str(routine.id),
                "feedback": body.feedback or "",
            },
        ),
        media_type="text/event-stream",
    )
