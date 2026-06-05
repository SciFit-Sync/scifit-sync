"""루틴 도메인 엔드포인트 — POST /routines/generate, /routines/{id}/regenerate SSE 스트리밍."""

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_required_profile
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.limiter import rate_limit
from app.models import (
    Equipment,
    EquipmentBrand,
    Exercise,
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
    WorkoutLog,
    WorkoutLogSet,
    WorkoutRoutine,
    WorkoutStatus,
)
from app.models import (
    UserProfile as DBUserProfile,
)
from app.models.gym import GymEquipment, UserGym
from app.models.routine import GeneratedBy, SplitType
from app.schemas.common import SuccessResponse
from app.schemas.routines import (
    AIRoutineDetail,
    ExerciseDetailItem,
    GenerateRoutineRequest,
    GymSummary,
    MuscleActivationDetailItem,
    MuscleActivationItem,
    PaperItem,
    RegenerateRoutineRequest,
    RoutineDayItem,
    RoutineDeleteData,
    RoutineDetail,
    RoutineExerciseItem,
    RoutineExercisePapersData,
    RoutineListData,
    RoutineSummary,
    SetItem,
    UpdateRoutineExerciseRequest,
    UpdateRoutineNameRequest,
)
from app.services.rag import UserProfile as RagUserProfile
from app.services.rag import routine_rag_stream
from app.services.routine_targets import derive_exercise_targets
from app.services.workoutx import get_exercise_by_name, to_gif_proxy_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routines", tags=["routines"])

# 루틴 생성 시 프론트에서 전송하는 영어 부위 키 → 한국어 표시명
_BODY_PART_KO: dict[str, str] = {
    "chest": "가슴",
    "back": "등",
    "shoulder": "어깨",
    "legs": "하체",
    "arms": "팔",
    "abs": "복근",
}


def _routine_to_summary(
    r: WorkoutRoutine,
    gym_name: str | None = None,
) -> RoutineSummary:
    target_muscle_names: list[str] | None = None
    if r.target_muscle_group_ids:
        names = [_BODY_PART_KO.get(mid, mid) for mid in r.target_muscle_group_ids]
        target_muscle_names = names or None
    return RoutineSummary(
        routine_id=str(r.id),
        name=r.name,
        fitness_goals=r.fitness_goals,
        target_muscle_names=target_muscle_names,
        split_type=str(r.split_type) if r.split_type else None,
        generated_by=str(r.generated_by) if r.generated_by else "user",
        status=str(r.status) if r.status else "active",
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
    ex_name_en_map: dict[str, str | None] = {}
    ex_gif_map: dict[str, str | None] = {}
    if ex_ids:
        rows = (
            await db.execute(
                select(Exercise.id, Exercise.name, Exercise.name_en, Exercise.gif_url).where(Exercise.id.in_(ex_ids))
            )
        ).all()
        ex_name_map = {str(eid): name for eid, name, _, _ in rows}
        ex_name_en_map = {str(eid): name_en for eid, _, name_en, _ in rows}
        ex_gif_map = {str(eid): gif for eid, _, _, gif in rows}

    # gif_url 캐싱 전략:
    #   None  → 아직 WorkoutX 미조회. 이번 요청에서 API 호출 후 결과를 DB에 저장.
    #   ""    → sentinel. WorkoutX 조회했으나 결과 없음. 재호출 방지용.
    #           `if exercise.gif_url:` 같은 단순 truthy 체크를 하면 None과 동일하게
    #           동작하므로, 이 컬럼을 직접 읽을 때는 `is None` 비교를 사용할 것.
    #           응답 시에는 `v or None`으로 클라이언트에 null로 내려간다.
    #   URL   → 캐시된 GIF URL. DB에서 바로 반환.
    # NOTE: 조회 함수지만 write-back을 위해 UPDATE+commit이 발생한다.
    gif_url_map: dict[str, str | None] = {k: v or None for k, v in ex_gif_map.items()}
    missing = [(str(eid), ex_name_en_map.get(str(eid))) for eid in ex_ids if ex_gif_map.get(str(eid)) is None]
    if missing:
        wx_results = await asyncio.gather(
            *[get_exercise_by_name(name_en) if name_en else asyncio.sleep(0, result=None) for _, name_en in missing],
            return_exceptions=True,
        )
        writes: list[tuple[str, str]] = []
        for (eid_str, name_en), wx in zip(missing, wx_results, strict=True):
            if isinstance(wx, dict):
                url = wx.get("gifUrl")
                gif_url_map[eid_str] = url
                writes.append((eid_str, url or ""))
            elif wx is None and name_en:
                # WorkoutX가 None 반환 = 확정 not-found(404) → sentinel 저장
                # Exception 인스턴스는 일시 장애이므로 sentinel 저장 안 함
                writes.append((eid_str, ""))
        try:
            for eid_str, gif_val in writes:
                await db.execute(update(Exercise).where(Exercise.id == uuid.UUID(eid_str)).values(gif_url=gif_val))
            if writes:
                await db.commit()
        except Exception:
            logger.warning("gif_url write-back 실패 — 조회 결과는 정상 반환")
            await db.rollback()

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
    # activation_pct가 NULL이면 involvement 기반으로 추정값 계산
    # primary끼리 70% 균등 분배, secondary끼리 30% 균등 분배 (primary만 있으면 100%)
    # 합계가 반드시 100이 되도록 마지막 항목에 나머지 할당 (반올림 오차 제거)
    def _split_pct(names: list[str], total: int) -> list[MuscleActivationItem]:
        """total을 names에 균등 분배, 합계가 정확히 total."""
        if not names:
            return []
        n = len(names)
        base = total // n
        remainder = total % n
        return [
            MuscleActivationItem(muscle=name, activation_pct=base + (1 if i < remainder else 0))
            for i, name in enumerate(names)
        ]

    muscle_activation_map: dict[str, list[MuscleActivationItem]] = {}
    if ex_ids:
        ma_rows = (
            await db.execute(
                select(
                    ExerciseMuscle.exercise_id,
                    MuscleGroup.name_ko,
                    ExerciseMuscle.activation_pct,
                    ExerciseMuscle.involvement,
                )
                .join(MuscleGroup, MuscleGroup.id == ExerciseMuscle.muscle_group_id)
                .where(
                    ExerciseMuscle.exercise_id.in_(ex_ids),
                )
                .distinct()
            )
        ).all()

        # 운동별 임시 수집
        _raw: dict[str, list[tuple[str, int | None, str | None]]] = {}
        for eid, name_ko, pct, involvement in ma_rows:
            _raw.setdefault(str(eid), []).append((name_ko, pct, involvement))

        for eid, muscles in _raw.items():
            # 모든 근육에 실제 activation_pct가 있을 때만 합계 100으로 정규화
            # 하나라도 NULL이면 involvement 기반 추정으로 fallback (NULL 근육이 0%로 묻히는 것 방지)
            if all(pct is not None for _, pct, _ in muscles):
                raw_pairs = [(name, pct or 0) for name, pct, _ in muscles]
                total = sum(p for _, p in raw_pairs)
                if total > 0 and total != 100:
                    running = 0
                    normalized: list[MuscleActivationItem] = []
                    for i, (name, pct) in enumerate(raw_pairs):
                        if i == len(raw_pairs) - 1:
                            normalized.append(MuscleActivationItem(muscle=name, activation_pct=100 - running))
                        else:
                            scaled = round(pct * 100 / total)
                            running += scaled
                            normalized.append(MuscleActivationItem(muscle=name, activation_pct=scaled))
                    muscle_activation_map[eid] = normalized
                else:
                    muscle_activation_map[eid] = [
                        MuscleActivationItem(muscle=name, activation_pct=pct or 0) for name, pct, _ in muscles
                    ]
                continue

            # activation_pct 없으면 involvement 기반 추정 (합계 정확히 100)
            primaries = [name for name, _, inv in muscles if inv == "primary"]
            secondaries = [name for name, _, inv in muscles if inv != "primary"]
            n_p, n_s = len(primaries), len(secondaries)

            if n_p > 0 and n_s > 0:
                items = _split_pct(primaries, 70) + _split_pct(secondaries, 30)
            elif n_p > 0:
                items = _split_pct(primaries, 100)
            else:
                items = _split_pct(secondaries, 100)

            muscle_activation_map[eid] = items

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
                gif_url=to_gif_proxy_url(gif_url_map.get(str(ex.exercise_id)), get_settings().PUBLIC_BASE_URL),
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
        split_type=str(r.split_type) if r.split_type else None,
        generated_by=str(r.generated_by) if r.generated_by else "user",
        status=str(r.status) if r.status else "active",
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
    response_model=SuccessResponse[RoutineExerciseItem],
    summary="루틴 운동 부분 수정 (PATCH semantics — 보낸 필드만 업데이트)",
)
async def update_routine_exercise(
    routine_id: str,
    routine_exercise_id: str,
    body: UpdateRoutineExerciseRequest,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    if all(
        v is None
        for v in [
            body.exercise_id,
            body.sets,
            body.reps_min,
            body.reps_max,
            body.weight_kg,
            body.rest_seconds,
            body.note,
        ]
    ):
        raise ValidationError(message="변경할 필드를 최소 하나 이상 입력해주세요.")
    routine = await _get_my_routine(routine_id, current_user, db)
    rex_id = _parse_uuid(routine_exercise_id, "routine_exercise_id")
    rex = (await db.execute(select(RoutineExercise).where(RoutineExercise.id == rex_id))).scalar_one_or_none()
    if rex is None:
        raise NotFoundError(message="루틴 내 운동을 찾을 수 없습니다.")

    # 종목 교체
    if body.exercise_id is not None:
        new_ex_id = _parse_uuid(body.exercise_id, "exercise_id")
        new_ex = (await db.execute(select(Exercise).where(Exercise.id == new_ex_id))).scalar_one_or_none()
        if new_ex is None:
            raise NotFoundError(message="운동을 찾을 수 없습니다.")
        rex.exercise_id = new_ex_id
        # PR-4: equipment_id NOT NULL — 같은 요청에 equipment_id가 없으면 결정론적으로 재선택.
        # _pick_equipment_for_exercise가 헬스장 머신/공통 프리웨이트만 고르므로 D-M9 소속 검증을 겸한다.
        if body.equipment_id is None:
            picked = await _pick_equipment_for_exercise(new_ex_id, routine.gym_id, db)
            if picked is None:
                raise ConflictError(message="교체할 운동에 사용할 수 있는 기구가 헬스장에 없습니다.")
            rex.equipment_id = picked

    # 기구 변경
    if body.equipment_id is not None:
        eq_id = _parse_uuid(body.equipment_id, "equipment_id")
        if routine.gym_id:
            gym_eq_ids = {
                row[0]
                for row in (
                    await db.execute(select(GymEquipment.equipment_id).where(GymEquipment.gym_id == routine.gym_id))
                ).all()
            }
            if eq_id not in gym_eq_ids:
                raise ConflictError(message="선택한 기구가 헬스장에 등록되어 있지 않습니다.")
        rex.equipment_id = eq_id

    # reps_min ≤ reps_max 검증 (기존값과 혼합 고려)
    effective_min = body.reps_min if body.reps_min is not None else rex.reps_min
    effective_max = body.reps_max if body.reps_max is not None else rex.reps_max
    if effective_min is not None and effective_max is not None and effective_min > effective_max:
        raise ValidationError(message="reps_min은 reps_max보다 작거나 같아야 합니다.")

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

    exercise = (await db.execute(select(Exercise).where(Exercise.id == rex.exercise_id))).scalar_one_or_none()
    equipment: Equipment | None = None
    if rex.equipment_id:
        equipment = (await db.execute(select(Equipment).where(Equipment.id == rex.equipment_id))).scalar_one_or_none()

    return SuccessResponse(
        data=RoutineExerciseItem(
            routine_exercise_id=str(rex.id),
            exercise_id=str(rex.exercise_id),
            exercise_name=exercise.name,
            equipment_id=str(rex.equipment_id) if rex.equipment_id else None,
            equipment_name=equipment.name if equipment else None,
            order_index=rex.order_index,
            sets=rex.sets,
            reps_min=rex.reps_min,
            reps_max=rex.reps_max,
            weight_kg=rex.weight_kg,
            rest_seconds=rex.rest_seconds,
            note=rex.note,
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


# ── GET /routines/{id}/ai-detail ──────────────────────────────────────────────
@router.get(
    "/{routine_id}/ai-detail",
    response_model=SuccessResponse[AIRoutineDetail],
    summary="AI 루틴 상세 조회",
)
async def get_ai_routine_detail(
    routine_id: str,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    routine = await _get_my_routine(routine_id, current_user, db)

    # 1. RoutineDay + RoutineExercise
    days_result = await db.execute(
        select(RoutineDay)
        .where(RoutineDay.routine_id == routine.id)
        .options(selectinload(RoutineDay.exercises))
        .order_by(RoutineDay.day_number)
    )
    days = days_result.scalars().unique().all()

    all_rex: list[RoutineExercise] = []
    for d in days:
        all_rex.extend(sorted(d.exercises, key=lambda e: e.order_index))

    # 2. Exercise batch fetch
    ex_ids = list({rex.exercise_id for rex in all_rex})
    ex_map: dict[uuid.UUID, Exercise] = {}
    if ex_ids:
        rows = (await db.execute(select(Exercise).where(Exercise.id.in_(ex_ids)))).scalars().all()
        ex_map = {e.id: e for e in rows}

    # 3. 근육 활성화 batch fetch
    muscle_map: dict[uuid.UUID, list[MuscleActivationDetailItem]] = {}
    if ex_ids:
        ma_rows = (
            await db.execute(
                select(ExerciseMuscle, MuscleGroup)
                .join(MuscleGroup, MuscleGroup.id == ExerciseMuscle.muscle_group_id)
                .where(ExerciseMuscle.exercise_id.in_(ex_ids))
            )
        ).all()
        for em, mg in ma_rows:
            muscle_map.setdefault(em.exercise_id, []).append(
                MuscleActivationDetailItem(
                    muscle=mg.name_ko,
                    muscle_en=mg.name,
                    percentage=em.activation_pct,
                    type=str(em.involvement),
                )
            )

    # 4. 활성 워크아웃 세션 조회 → set 완료 상태 오버레이
    day_ids = [d.id for d in days]
    completed_sets_map: dict[uuid.UUID, dict[int, WorkoutLogSet]] = {}
    if day_ids:
        active_log = (
            await db.execute(
                select(WorkoutLog)
                .where(
                    WorkoutLog.user_id == current_user.id,
                    WorkoutLog.routine_day_id.in_(day_ids),
                    WorkoutLog.status == WorkoutStatus.IN_PROGRESS,
                )
                .order_by(WorkoutLog.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if active_log:
            log_sets = (
                (
                    await db.execute(
                        select(WorkoutLogSet)
                        .where(WorkoutLogSet.workout_log_id == active_log.id)
                        .order_by(WorkoutLogSet.set_number)
                    )
                )
                .scalars()
                .all()
            )
            for s in log_sets:
                if s.routine_exercise_id:
                    completed_sets_map.setdefault(s.routine_exercise_id, {})[s.set_number] = s

    # 5. WorkoutX API 병렬 호출 (thumbnail/equipment 등 메타데이터 포함, 전체 운동 대상)
    # gif_url write-back은 DB에 없는 운동만 수행해 중복 호출을 줄인다.
    unique_exs = list(ex_map.values())
    wx_results = await asyncio.gather(
        *[get_exercise_by_name(e.name_en) if e.name_en else asyncio.sleep(0, result=None) for e in unique_exs],
        return_exceptions=True,
    )
    wx_map: dict[uuid.UUID, dict] = {
        e.id: r for e, r in zip(unique_exs, wx_results, strict=True) if isinstance(r, dict)
    }

    # gif_url: DB 저장값 우선, IS NULL인 운동만 WorkoutX 결과로 write-back
    gif_url_map: dict[uuid.UUID, str | None] = {e.id: e.gif_url or None for e in ex_map.values()}
    writes: list[tuple[uuid.UUID, str]] = []
    for ex, wx in zip(unique_exs, wx_results, strict=True):
        if ex.gif_url is not None:
            continue  # 이미 캐시됨 — write-back 불필요
        if isinstance(wx, dict):
            url = wx.get("gifUrl")
            gif_url_map[ex.id] = url
            writes.append((ex.id, url or ""))
        elif wx is None and ex.name_en:
            writes.append((ex.id, ""))
    try:
        for eid, gif_val in writes:
            await db.execute(update(Exercise).where(Exercise.id == eid).values(gif_url=gif_val))
        if writes:
            await db.commit()
    except Exception:
        logger.warning("gif_url write-back 실패 — 조회 결과는 정상 반환")
        await db.rollback()

    # 6. RoutinePaper 수 batch fetch → tips_count / tips_available 계산용
    rex_ids = [rex.id for rex in all_rex]
    paper_counts: dict[uuid.UUID, int] = {}
    if rex_ids:
        count_rows = (
            await db.execute(
                select(RoutinePaper.routine_exercise_id, func.count().label("cnt"))
                .where(
                    RoutinePaper.routine_id == routine.id,
                    RoutinePaper.routine_exercise_id.in_(rex_ids),
                )
                .group_by(RoutinePaper.routine_exercise_id)
            )
        ).all()
        paper_counts = {rex_id: cnt for rex_id, cnt in count_rows}

    # 7. ExerciseDetailItem 빌드
    exercise_items: list[ExerciseDetailItem] = []
    for order_idx, rex in enumerate(all_rex, start=1):
        ex = ex_map.get(rex.exercise_id)
        if ex is None:
            continue
        wx = wx_map.get(rex.exercise_id, {})
        sets_by_num = completed_sets_map.get(rex.id, {})

        reps = rex.reps_min or 10
        if rex.reps_min and rex.reps_max:
            reps = (rex.reps_min + rex.reps_max) // 2

        set_items: list[SetItem] = []
        for set_num in range(1, rex.sets + 1):
            log_set = sets_by_num.get(set_num)
            set_items.append(
                SetItem(
                    set_number=set_num,
                    weight_kg=log_set.weight_kg if log_set else rex.weight_kg,
                    reps=log_set.reps if log_set else reps,
                    rest_seconds=0 if set_num == rex.sets else rex.rest_seconds,
                    completed=log_set.is_completed if log_set else False,
                    completed_at=log_set.performed_at if (log_set and log_set.is_completed) else None,
                )
            )

        exercise_items.append(
            ExerciseDetailItem(
                order=order_idx,
                exercise_id=str(rex.exercise_id),
                name=ex.name,
                name_en=ex.name_en,
                gif_url=to_gif_proxy_url(gif_url_map.get(rex.exercise_id), get_settings().PUBLIC_BASE_URL),
                thumbnail_url=wx.get("thumbnailUrl"),
                category=ex.category,
                equipment=wx.get("equipment"),
                difficulty=wx.get("difficulty"),
                mechanic=wx.get("mechanic"),
                force=wx.get("force"),
                muscle_activation=muscle_map.get(rex.exercise_id, []),
                sets=set_items,
                tips_count=paper_counts.get(rex.id, 0),
                tips_available=paper_counts.get(rex.id, 0) > 0,
                calories_per_minute=wx.get("caloriesPerMinute"),
                met=wx.get("met"),
                is_replaceable=True,
            )
        )

    # default_rest_seconds: 가장 빈도 높은 rest_seconds (0 제외)
    rest_vals = [rex.rest_seconds for rex in all_rex if rex.rest_seconds > 0]
    default_rest = max(set(rest_vals), key=rest_vals.count) if rest_vals else 60

    return SuccessResponse(
        data=AIRoutineDetail(
            routine_id=str(routine.id),
            title=routine.name,
            goal=routine.fitness_goals[0] if routine.fitness_goals else None,
            estimated_duration_min=routine.session_minutes,
            default_rest_seconds=default_rest,
            created_by=str(routine.generated_by),
            created_at=routine.created_at,
            exercises=exercise_items,
        )
    )


# ── RAG/SSE 공통 헬퍼 ─────────────────────────────────────────────────────────


def _sse(seq: int, payload: dict) -> str:
    """SSE 한 이벤트 직렬화. 한국어가 그대로 흘러갈 수 있도록 ensure_ascii=False."""
    return f"id: evt_{seq:03d}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_done() -> str:
    """SSE 종료 마커. CLAUDE.md §7 명세."""
    return "data: [DONE]\n\n"


async def _async_iter_sync_gen(make_gen):
    """블로킹 sync generator를 별도 스레드로 격리해 async iterator로 노출."""
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


async def _resolve_primary_gym_id(user_id: uuid.UUID, db: AsyncSession) -> str | None:
    """user의 기본 헬스장 gym_id(is_primary 우선). gym_id 미지정 루틴 생성 시 fallback (D-M9).

    프론트가 routine 생성 요청에 gym_id를 보내지 않아도, 서버가 user_gyms의 기본 헬스장을
    채워 머신 후보(gym_equipments 기반)가 _build_rag_profile에서 정상 생성되도록 한다.
    user_gyms가 없으면 None(전 헬스장 공통 프리/맨몸만 — else fallback).
    """
    row = (
        await db.execute(
            select(UserGym.gym_id).where(UserGym.user_id == user_id).order_by(UserGym.is_primary.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return str(row) if row else None


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

    req: GenerateRoutineRequest | None = overrides or (body if isinstance(body, GenerateRoutineRequest) else None)

    # 3. target_muscle_group_ids → UUID 또는 body_region 문자열로 해석
    _REGION_ALIASES: dict[str, str] = {
        "shoulder": "shoulders",
        "shoulders": "shoulders",
        "back": "back",
        "chest": "chest",
        "legs": "legs",
        "leg": "legs",
        "arms": "arms",
        "arm": "arms",
        "abs": "core",
        "core": "core",
    }

    target_muscle_ids: list[uuid.UUID] = []
    target_muscle_names: list[str] = []
    body_regions: list[str] = []
    # 선택 순서 보존(복수 부위 비중 배분용): ("uuid", UUID) | ("region", str)
    priority_specs: list[tuple[str, object]] = []
    if req and req.target_muscle_group_ids:
        for mid in req.target_muscle_group_ids:
            if not mid:
                continue
            try:
                uid = uuid.UUID(mid)
                target_muscle_ids.append(uid)
                priority_specs.append(("uuid", uid))
            except ValueError:
                normalized = _REGION_ALIASES.get(mid.lower(), mid.lower())
                body_regions.append(normalized)
                priority_specs.append(("region", normalized))

    if body_regions:
        region_rows = (await db.execute(select(MuscleGroup.id).where(MuscleGroup.body_region.in_(body_regions)))).all()
        target_muscle_ids.extend([row[0] for row in region_rows])

    target_priority: list[str] = []
    if target_muscle_ids:
        mg_rows = (
            await db.execute(select(MuscleGroup.id, MuscleGroup.name).where(MuscleGroup.id.in_(target_muscle_ids)))
        ).all()
        target_muscle_names = [name for _, name in mg_rows]
        # 선택 순서대로 우선순위 라벨 구성 (region은 라벨 그대로, uuid는 근육명) + 중복 제거
        id_to_name = {str(mid): name for mid, name in mg_rows}
        seen_pri: set[str] = set()
        for kind, val in priority_specs:
            label = val if kind == "region" else id_to_name.get(str(val))
            if label and label not in seen_pri:
                seen_pri.add(label)
                target_priority.append(label)

    # 5. gym 기구 × 선택 근육 필터링 → LLM에게 전달할 기구 목록 (PR-3: 기구 중심 재설계)
    #    머신(is_freeweight=false): gym_equipments(gym_id) × equipment_muscles(근육 필터, optional)
    #    프리웨이트(is_freeweight=true): exercise_muscles × exercises × equipments(default_equipment_id), 전 헬스장 공통
    #    gym_id 있는데 결과 0개 → 404 (전체 DB로 새지 않음)
    #    gym_id 없을 때만 전체 DB 허용 (fallback)
    from app.models.gym import EquipmentMuscle

    available_equipments: list[dict] = []
    gym_id_str = req.gym_id if req else None
    gid: uuid.UUID | None = None

    if gym_id_str:
        try:
            gid = uuid.UUID(gym_id_str)
        except ValueError:
            logger.warning("gym_id가 UUID가 아님: %s", gym_id_str)

    if gid is not None:
        # ── 머신 후보: gym_equipments JOIN equipments(is_freeweight=false) ──
        machine_stmt = (
            select(
                Equipment.id,
                Equipment.movement_label_en,
                Equipment.name_en,
                Equipment.name,
                Equipment.equipment_type,
            )
            .join(GymEquipment, GymEquipment.equipment_id == Equipment.id)
            .where(
                GymEquipment.gym_id == gid,
                Equipment.is_freeweight == False,  # noqa: E712
            )
        )
        if target_muscle_ids:
            machine_stmt = machine_stmt.join(EquipmentMuscle, EquipmentMuscle.equipment_id == Equipment.id).where(
                EquipmentMuscle.muscle_group_id.in_(target_muscle_ids),
                EquipmentMuscle.involvement == "primary",
            )
        machine_stmt = machine_stmt.distinct().order_by(Equipment.movement_label_en, Equipment.name_en, Equipment.name)
        machine_rows = (await db.execute(machine_stmt)).all()

        for row in machine_rows:
            label = row.movement_label_en or row.name_en or row.name
            if not label:
                continue
            available_equipments.append(
                {
                    "equipment_id": str(row.id),
                    "label": label.strip(),
                    "equipment_type": str(row.equipment_type),
                    "source": "MACHINE",
                }
            )

        # ── 프리웨이트 후보: exercise_muscles × exercises × equipments(default_equipment_id, is_freeweight=true) ──
        # 전 헬스장 공통 — gym 필터 없음 (PR-4.5: exercise_equipment_map → exercises.default_equipment_id)
        free_stmt = (
            select(
                Exercise.id.label("exercise_id"),
                Exercise.name_en.label("exercise_name_en"),
                Equipment.id.label("equipment_id"),
                Equipment.equipment_type,
            )
            .join(ExerciseMuscle, ExerciseMuscle.exercise_id == Exercise.id)
            .join(Equipment, Equipment.id == Exercise.default_equipment_id)
            .where(
                Exercise.name_en.isnot(None),
                Equipment.is_freeweight == True,  # noqa: E712
            )
        )
        if target_muscle_ids:
            free_stmt = free_stmt.where(
                ExerciseMuscle.muscle_group_id.in_(target_muscle_ids),
                ExerciseMuscle.involvement == "primary",
            )
        free_stmt = free_stmt.distinct().order_by(Exercise.name_en)
        free_rows = (await db.execute(free_stmt)).all()

        # 중복 label 제거 (exercise_name_en 기준)
        seen_free_labels: set[str] = set()
        for row in free_rows:
            label = (row.exercise_name_en or "").strip()
            if not label or label in seen_free_labels:
                continue
            seen_free_labels.add(label)
            available_equipments.append(
                {
                    "equipment_id": str(row.equipment_id),
                    "label": label,
                    "equipment_type": str(row.equipment_type),
                    "source": "FREE",
                }
            )

        # gym_id 있는데 후보 0개 → 404 (전체 DB fallback 없음, 스펙 §3-B.4)
        if not available_equipments:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(
                message="해당 헬스장에 등록된 기구가 없습니다. 기구를 먼저 등록해 주세요.",
                details={"gym_id": gym_id_str, "reason": "no_gym_equipments"},
            )

    else:
        # gym_id 없을 때: 전체 DB 기준 프리웨이트 + 머신 (순수 fallback)
        fb_free_stmt = (
            select(
                Exercise.name_en.label("exercise_name_en"),
                Equipment.id.label("equipment_id"),
                Equipment.equipment_type,
            )
            .join(ExerciseMuscle, ExerciseMuscle.exercise_id == Exercise.id)
            .join(Equipment, Equipment.id == Exercise.default_equipment_id)
            .where(
                Exercise.name_en.isnot(None),
                Equipment.is_freeweight == True,  # noqa: E712
            )
        )
        if target_muscle_ids:
            fb_free_stmt = fb_free_stmt.where(
                ExerciseMuscle.muscle_group_id.in_(target_muscle_ids),
                ExerciseMuscle.involvement == "primary",
            )
        fb_free_stmt = fb_free_stmt.distinct().order_by(Exercise.name_en)
        fb_free_rows = (await db.execute(fb_free_stmt)).all()

        seen_fb: set[str] = set()
        for row in fb_free_rows:
            label = (row.exercise_name_en or "").strip()
            if not label or label in seen_fb:
                continue
            seen_fb.add(label)
            available_equipments.append(
                {
                    "equipment_id": str(row.equipment_id),
                    "label": label,
                    "equipment_type": str(row.equipment_type),
                    "source": "FREE",
                }
            )

    return RagUserProfile(
        goals=(req.goals if req else []),
        body_weight=body_weight,
        fitness_career=str(profile.career_level),
        gender=str(profile.gender) if profile.gender else None,
        available_equipments=available_equipments,
        target_muscles=target_muscle_names,
        target_priority=target_priority,
        session_minutes=(req.session_minutes if req else None),
        injury=(req.injury if req else None),
        feedback=feedback,
    )


async def _resolve_exercise_id(name: str, db: AsyncSession) -> uuid.UUID | None:
    """[DEPRECATED · 호출처 없음] LLM 운동 이름 → exercises.id 의 fuzzy 매칭.

    _resolve_label_to_ids의 fuzzy fallback이 머신→프리웨이트 오매칭(예: "Chest Press"→
    "Bench Press")을 유발해 제거되면서 호출처가 사라졌다. 향후 다른 용도로 재사용할
    여지가 있어 함수는 보존하되, 어떤 런타임 경로에서도 호출하지 않는다.

    순서:
    1) name_en 정확 매치 (case-insensitive)
    2) name(한글) 정확 매치
    3) DB name_en이 LLM 이름을 포함 (DB가 더 긴 경우)
    4) LLM 이름이 DB name_en을 포함 (LLM이 더 구체적인 경우, e.g. "Flat Barbell Bench Press" → "Bench Press")
    5) 토큰 겹침 매치 — 최소 2 토큰 공통 (e.g. "Incline Dumbbell Press" → "Incline Bench Press")
    """
    if not name or not name.strip():
        return None
    name_lc = name.strip().lower()

    from sqlalchemy import func as sa_func

    # 1) name_en 정확 매치
    row = (
        await db.execute(select(Exercise.id).where(sa_func.lower(Exercise.name_en) == name_lc).limit(1))
    ).scalar_one_or_none()
    if row is not None:
        return row

    # 2) name (한글) 정확 매치
    row = (await db.execute(select(Exercise.id).where(Exercise.name == name.strip()).limit(1))).scalar_one_or_none()
    if row is not None:
        return row

    # 3) DB name_en이 LLM 이름을 포함 (LLM 이름이 더 짧은 경우)
    row = (
        await db.execute(select(Exercise.id).where(Exercise.name_en.ilike(f"%{name.strip()}%")).limit(1))
    ).scalar_one_or_none()
    if row is not None:
        return row

    # 4 & 5) 전체 exercise 목록으로 Python-side 매칭 (테이블 소규모)
    all_exercises = (await db.execute(select(Exercise.id, Exercise.name_en))).all()
    name_tokens = set(name_lc.split())

    # 4) 역방향 부분 매치: LLM 이름이 DB name_en을 포함하는 경우 (가장 긴 매치 우선)
    best_id: uuid.UUID | None = None
    best_len = 0
    for ex_id, ex_name_en in all_exercises:
        if not ex_name_en:
            continue
        candidate = ex_name_en.strip().lower()
        if candidate and candidate in name_lc and len(candidate) > best_len:
            best_id = ex_id
            best_len = len(candidate)
    if best_id is not None:
        return best_id

    # 5) 토큰 겹침 매치: 공통 단어 수가 많은 운동 선택 (최소 2 토큰)
    best_overlap = 1  # > 1 이어야 선택 (최소 2 토큰 겹침)
    best_overlap_id: uuid.UUID | None = None
    for ex_id, ex_name_en in all_exercises:
        if not ex_name_en:
            continue
        db_tokens = set(ex_name_en.strip().lower().split())
        overlap = len(name_tokens & db_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_overlap_id = ex_id
    return best_overlap_id


async def _fetch_user_1rms(user_id: uuid.UUID, db: AsyncSession) -> dict[uuid.UUID, float]:
    """사용자의 운동별 1RM 매핑. exercise_id → weight_kg."""
    rows = (
        await db.execute(
            select(UserExercise1RM.exercise_id, UserExercise1RM.weight_kg).where(UserExercise1RM.user_id == user_id)
        )
    ).all()
    return {ex_id: float(w) for ex_id, w in rows}


async def _resolve_label_to_ids(
    label: str,
    gym_id: uuid.UUID | None,
    db: AsyncSession,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None, float, float | None]:
    """LLM equipment_label → (equipment_id, exercise_id, equipment_type, pulley_ratio, bar_weight).

    해석 순서:
    1) 머신: equipments.movement_label_en == label (gym_id가 있으면 gym_equipments 체크)
    2) 프리웨이트: exercises.name_en == label → exercises.default_equipment_id에서 기구 선택
    3) 정확 매칭 실패 시 제외 (fuzzy fallback 비활성 — 머신→프리 오매칭 방지)

    반환: (equipment_id, exercise_id, equipment_type, pulley_ratio, bar_weight)
    """
    from sqlalchemy import func as sa_func

    label_stripped = label.strip()
    label_lc = label_stripped.lower()

    # ── 1) 머신: movement_label_en 정확 매치 ──
    machine_stmt = select(Equipment.id, Equipment.equipment_type, Equipment.pulley_ratio, Equipment.bar_weight).where(
        sa_func.lower(Equipment.movement_label_en) == label_lc
    )
    if gym_id is not None:
        machine_stmt = machine_stmt.join(GymEquipment, GymEquipment.equipment_id == Equipment.id).where(
            GymEquipment.gym_id == gym_id
        )
    machine_stmt = machine_stmt.limit(1)
    machine_row = (await db.execute(machine_stmt)).first()

    if machine_row is not None:
        eq_id = machine_row.id
        eq_type = str(machine_row.equipment_type)
        pulley_ratio = float(machine_row.pulley_ratio)
        bar_weight = machine_row.bar_weight

        # movement_label_en == label이면 exercises.name_en도 동일 값으로 연결된다(스펙 §데이터모델)
        # exercises에서 name_en == label_stripped 인 exercise_id를 찾는다
        ex_row = (
            await db.execute(select(Exercise.id).where(sa_func.lower(Exercise.name_en) == label_lc).limit(1))
        ).scalar_one_or_none()
        return eq_id, ex_row, eq_type, pulley_ratio, bar_weight

    # ── 2) 프리웨이트: exercises.name_en 정확 매치 ──
    ex_row = (
        await db.execute(
            select(Exercise.id, Exercise.default_equipment_id)
            .where(sa_func.lower(Exercise.name_en) == label_lc)
            .limit(1)
        )
    ).first()

    if ex_row is not None:
        exercise_id = ex_row.id
        # PR-4.5: 프리웨이트 운동의 구현 기구는 exercises.default_equipment_id (exercise_equipment_map 대체)
        if ex_row.default_equipment_id is not None:
            eq_row = (
                await db.execute(
                    select(Equipment.equipment_type, Equipment.pulley_ratio, Equipment.bar_weight)
                    .where(Equipment.id == ex_row.default_equipment_id)
                    .limit(1)
                )
            ).first()
            if eq_row is not None:
                return (
                    ex_row.default_equipment_id,
                    exercise_id,
                    str(eq_row.equipment_type),
                    float(eq_row.pulley_ratio),
                    eq_row.bar_weight,
                )
        # 기구 매핑 없어도 exercise_id는 반환 (equipment_id None)
        return None, exercise_id, None, 1.0, None

    # ── 3) 정확 매칭 실패 → 제외 (fuzzy fallback 제거) ──
    # 기존 _resolve_exercise_id fuzzy("Chest Press"→"Bench Press" 등 부분/토큰 매칭)는
    # LLM이 목록 밖 label을 내면 엉뚱한 운동(특히 머신→프리웨이트)으로 둔갑시켜
    # "체스트 프레스 머신 선택했는데 벤치프레스 표시" 문제를 유발했다. LLM은 프롬프트로
    # available_equipments의 label만 출력하도록 강제되므로, 정확 매칭(머신 movement_label_en /
    # 프리 name_en) 실패 시 fuzzy로 추정하지 않고 해당 운동을 제외한다(_persist_day에서 skip).
    logger.warning("equipment_label '%s' 정확 매칭 실패 — 해당 운동 제외 (fuzzy 비활성)", label_stripped)
    return None, None, None, 1.0, None


async def _pick_equipment_for_exercise(
    exercise_id: uuid.UUID,
    gym_id: uuid.UUID | None,
    db: AsyncSession,
) -> uuid.UUID | None:
    """exercise_id에 맞는 기구를 결정론적으로 1개 선택한다 (equipment_id NOT NULL 보장용, PATCH 종목 교체).

    운동은 프리웨이트이거나 머신 movement_template 둘 중 하나다(disjoint):
      - 프리웨이트: exercises.default_equipment_id (전 헬스장 공통, gym 제약 없음).
      - 머신: equipments.movement_label_en == exercises.name_en 인 기구를 gym 보유분에서 선택.
    선택 불가 시 None (PATCH 호출부에서 409).
    """
    from sqlalchemy import func as sa_func

    ex_row = (
        await db.execute(select(Exercise.name_en, Exercise.default_equipment_id).where(Exercise.id == exercise_id))
    ).first()
    if ex_row is None:
        return None

    # 프리웨이트: 전 헬스장 공통 기구
    if ex_row.default_equipment_id is not None:
        return ex_row.default_equipment_id

    # 머신: movement_label_en == name_en 인 기구 (gym 지정 시 그 헬스장 보유분만)
    if not ex_row.name_en:
        return None
    machine_stmt = select(Equipment.id).where(sa_func.lower(Equipment.movement_label_en) == ex_row.name_en.lower())
    if gym_id is not None:
        machine_stmt = machine_stmt.join(GymEquipment, GymEquipment.equipment_id == Equipment.id).where(
            GymEquipment.gym_id == gym_id
        )
    machine_stmt = machine_stmt.order_by(Equipment.id).limit(1)
    row = (await db.execute(machine_stmt)).first()
    return row[0] if row else None


async def _persist_day(
    *,
    routine_id: uuid.UUID,
    day_data: dict,
    primary_goal: str,
    user_1rms: dict[uuid.UUID, float],
    user_body_weight: float,
    user_gender: str | None,
    user_career_level: str | None,
    gym_id: uuid.UUID | None,
    db: AsyncSession,
) -> tuple[RoutineDay, list[tuple[RoutineExercise, int | None]], list[uuid.UUID]]:
    """LLM day_complete 이벤트를 RoutineDay + RoutineExercise[] 로 저장하고 (day, exercise_pairs, dropped) 반환.

    PR-3: LLM은 equipment_label을 출력. _resolve_label_to_ids가 label → (equipment_id, exercise_id)로 변환.
    exercise_id NOT NULL이 필수 — 해석 실패(None) 시 해당 운동 제외.
    """
    day_number = int(day_data.get("day") or 1)
    label = str(day_data.get("focus") or f"Day {day_number}")[:200]

    day = RoutineDay(routine_id=routine_id, day_number=day_number, label=label)
    db.add(day)
    await db.flush()  # day.id 확보

    exercise_pairs: list[tuple[RoutineExercise, int | None]] = []
    llm_exercises = day_data.get("exercises") or []
    for idx, ex_data in enumerate(llm_exercises):
        if not isinstance(ex_data, dict):
            continue

        # PR-3: LLM은 "name" 대신 "equipment_label" 출력; 하위 호환으로 "name" fallback
        equipment_label = str(ex_data.get("equipment_label") or ex_data.get("name") or "").strip()
        if not equipment_label:
            logger.warning("운동 항목에 equipment_label/name 없음 (idx=%d) — 제외", idx)
            continue

        eq_id, exercise_id, eq_type, pulley_ratio, bar_weight = await _resolve_label_to_ids(equipment_label, gym_id, db)

        if exercise_id is None:
            logger.warning("equipment_label '%s' exercise_id 해석 실패 — 제외", equipment_label)
            continue

        # PR-4: equipment_id NOT NULL — 기구 해석 실패 시 저장 불가하므로 제외
        if eq_id is None:
            logger.warning(
                "equipment_label '%s' equipment_id 해석 실패 — 제외 (equipment_id NOT NULL)", equipment_label
            )
            continue

        targets = derive_exercise_targets(
            goal=primary_goal,
            user_1rm_kg=user_1rms.get(exercise_id),
            user_body_weight=user_body_weight,
            user_gender=user_gender,
            user_career_level=user_career_level,
            equipment_type=eq_type,
            pulley_ratio=pulley_ratio,
            bar_weight=bar_weight,
            llm_sets=ex_data.get("sets"),
            llm_reps_min=ex_data.get("reps_min"),
            llm_reps_max=ex_data.get("reps_max"),
            llm_rest_seconds=ex_data.get("rest_seconds"),
        )

        # paper_index: LLM이 지정한 1-5 논문 번호 (없으면 None)
        raw_idx = ex_data.get("paper_index")
        try:
            paper_index: int | None = int(raw_idx) if raw_idx is not None else None
        except (TypeError, ValueError):
            paper_index = None

        rex = RoutineExercise(
            routine_day_id=day.id,
            exercise_id=exercise_id,
            equipment_id=eq_id,
            order_index=idx,
            sets=targets["sets"],
            reps_min=targets["reps_min"],
            reps_max=targets["reps_max"],
            weight_kg=targets["weight_kg"],
            rest_seconds=targets["rest_seconds"],
            note=(ex_data.get("notes") or None),
            display_name=equipment_label[:200],
        )
        db.add(rex)
        exercise_pairs.append((rex, paper_index))

    await db.flush()
    return day, exercise_pairs, []


async def _persist_papers(
    *,
    routine_id: uuid.UUID,
    sources: list[dict],
    exercise_paper_pending: list[tuple[uuid.UUID, int | None, str | None]],
    db: AsyncSession,
) -> int:
    """exercise_paper_pending의 각 운동을 sources와 매핑해 RoutinePaper에 저장. 삽입 건수 반환."""
    if not sources:
        return 0

    # DOI가 primary identifier (D-M11). PMID는 fallback.
    dois = [s.get("doi") for s in sources if s.get("doi")]
    pmids = [s.get("pmid") for s in sources if s.get("pmid")]
    if not dois and not pmids:
        return 0

    doi_to_id: dict[str, uuid.UUID] = {}
    pmid_to_id: dict[str, uuid.UUID] = {}

    if dois:
        rows = (await db.execute(select(Paper.id, Paper.doi).where(Paper.doi.in_(dois)))).all()
        doi_to_id = {doi: pid for pid, doi in rows}
    if pmids:
        rows = (await db.execute(select(Paper.id, Paper.pmid).where(Paper.pmid.in_(pmids)))).all()
        pmid_to_id = {pmid: pid for pid, pmid in rows}

    inserted = 0
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()  # (routine_exercise_id, paper_id) 중복 방지

    for rex_id, paper_index, notes_ko in exercise_paper_pending:
        # paper_index(1-based) → sources 인덱스(0-based). 범위 밖이면 0으로 fallback.
        src_idx = (paper_index - 1) if (paper_index and 1 <= paper_index <= len(sources)) else 0
        src = sources[src_idx]
        # DOI 우선 조회, 없으면 PMID fallback
        paper_id = doi_to_id.get(src.get("doi") or "") or pmid_to_id.get(src.get("pmid") or "")
        if paper_id is None:
            logger.warning("논문 매칭 실패 — doi=%s pmid=%s", src.get("doi"), src.get("pmid"))
            continue
        key = (rex_id, paper_id)
        if key in seen:
            continue
        seen.add(key)
        db.add(
            RoutinePaper(
                routine_id=routine_id,
                paper_id=paper_id,
                routine_exercise_id=rex_id,
                relevance_summary=notes_ko,
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
    delete_on_error: bool = False,
) -> AsyncIterator[str]:
    """공통 SSE 스트림: started → chunk*/day_complete*/papers → done → [DONE].

    delete_on_error=True 면 RAG 에러 시 routine 행을 DB에서 삭제하고 done 이벤트의
    routine_id를 비운다 (generate 경로 — 빈 좀비 루틴 방지). regenerate 경로는
    기존 루틴을 보존해야 하므로 기본값(False) 사용.
    """
    seq = 1
    yield _sse(seq, initial_event)

    primary_goal = profile.primary_goal
    user_1rms = await _fetch_user_1rms(user.id, db)

    # day_complete 처리 중 수집: (routine_exercise_id, paper_index, notes_ko)
    # papers 이벤트 도착 후 운동별 RoutinePaper 저장에 사용
    exercise_paper_pending: list[tuple[uuid.UUID, int | None, str | None]] = []

    error_emitted = False
    try:
        async for ev in _async_iter_sync_gen(lambda: routine_rag_stream(profile)):
            etype = ev.get("type")
            seq += 1

            if etype == "chunk":
                # 1초당 다수 토큰이 흐름. content는 그대로 노출.
                yield _sse(seq, {"type": "chunk", "content": ev.get("content", "")})

            elif etype == "day_complete":
                day, rex_pairs, _dropped = await _persist_day(
                    routine_id=routine.id,
                    day_data=ev,
                    primary_goal=primary_goal,
                    user_1rms=user_1rms,
                    user_body_weight=profile.body_weight,
                    user_gender=str(profile.gender) if profile.gender else None,
                    user_career_level=str(profile.fitness_career) if profile.fitness_career else None,
                    gym_id=routine.gym_id,
                    db=db,
                )
                # paper_index와 notes를 나중에 _persist_papers에서 사용하기 위해 수집
                for rex, paper_index in rex_pairs:
                    exercise_paper_pending.append((rex.id, paper_index, rex.note))

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
                                for rex, _ in rex_pairs
                            ],
                        },
                    },
                )

            elif etype == "papers":
                # papers 이벤트: 수집된 exercise_paper_pending과 연결하여 운동별 저장
                sources = ev.get("sources") or []
                await _persist_papers(
                    routine_id=routine.id,
                    sources=sources,
                    exercise_paper_pending=exercise_paper_pending,
                    db=db,
                )
                yield _sse(
                    seq,
                    {
                        "type": "paper_found",
                        "papers": [
                            {
                                "pmid": s.get("pmid"),
                                "title": s.get("title"),
                                "similarity": s.get("score"),
                            }
                            for s in sources
                        ],
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
        error_emitted = True
        seq += 1
        yield _sse(seq, {"type": "error", "message": f"내부 오류: {e}"})

    # 에러 발생 + 새로 만든 루틴(generate)인 경우: 빈 좀비 행을 삭제한다.
    # Core delete를 사용해 ORM 비동기 lazy-load(MissingGreenlet) 위험 회피;
    # FK들이 ON DELETE CASCADE이므로 자식(day/paper) 정리는 DB가 처리.
    if error_emitted and delete_on_error:
        try:
            await db.execute(sa_delete(WorkoutRoutine).where(WorkoutRoutine.id == routine.id))
            await db.commit()
            logger.info("RAG 에러로 빈 루틴 삭제: routine_id=%s", routine.id)
        except Exception:  # noqa: BLE001
            logger.exception("빈 루틴 삭제 실패: routine_id=%s", routine.id)
            await db.rollback()

    seq += 1
    # 에러 시엔 routine_id를 노출하지 않아 앱이 빈/삭제된 루틴을 조회하지 않게 함.
    done_payload: dict = {"type": "done"}
    if not error_emitted:
        done_payload["routine_id"] = str(routine.id)
    yield _sse(seq, done_payload)
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

    split = None
    if body.split_type:
        try:
            split = SplitType(body.split_type)
        except ValueError as e:
            valid = [e.value for e in SplitType]
            raise ValidationError(message=f"split_type 값이 올바르지 않습니다. 가능한 값: {valid}") from e
    # gym_id 미지정 시 user 기본 헬스장 자동 사용 (D-M9: 루틴은 gym 종속).
    # 프론트가 gym_id를 안 보내도 머신 후보가 나오도록 서버가 기본 gym을 채운다.
    if not body.gym_id:
        body.gym_id = await _resolve_primary_gym_id(current_user.id, db)
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
            delete_on_error=True,  # 새로 만든 routine이므로 RAG 실패 시 빈 행 삭제
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
        split_type=str(routine.split_type) if routine.split_type else None,
        gym_id=(str(routine.gym_id) if routine.gym_id else None) or await _resolve_primary_gym_id(current_user.id, db),
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
