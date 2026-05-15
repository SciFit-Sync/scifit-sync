"""세션(운동 로그) 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #29-36, #48.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    Exercise,
    RoutineExercise,
    User,
    WorkoutLog,
    WorkoutLogSet,
    WorkoutStatus,
)
from app.schemas.common import SuccessResponse
from app.schemas.sessions import (
    FinishSessionRequest,
    LogSetRequest,
    RestTimerData,
    SessionData,
    SessionDetail,
    SessionListData,
    SessionStatsData,
    StartSessionRequest,
    VolumeAnalysisData,
    VolumeAnalysisItem,
    WorkoutSetItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _parse_uuid(v: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise ValidationError(message=f"잘못된 {name} 형식입니다.") from e


def _session_to_dto(s: WorkoutLog) -> SessionData:
    return SessionData(
        session_id=str(s.id),
        routine_day_id=str(s.routine_day_id) if s.routine_day_id else None,
        gym_id=str(s.gym_id) if s.gym_id else None,
        started_at=s.started_at,
        finished_at=s.finished_at,
        status=s.status.value if s.status else "in_progress",
    )


async def _get_my_session(session_id: str, user: User, db: AsyncSession) -> WorkoutLog:
    sid = _parse_uuid(session_id, "session_id")
    s = (
        await db.execute(select(WorkoutLog).where(WorkoutLog.id == sid, WorkoutLog.user_id == user.id))
    ).scalar_one_or_none()
    if s is None:
        raise NotFoundError(message="세션을 찾을 수 없습니다.")
    return s


# ── POST /sessions ────────────────────────────────────────────────────────────
@router.post("", response_model=SuccessResponse[SessionData], status_code=201, summary="세션 시작")
async def start_session(
    body: StartSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine_day_id = _parse_uuid(body.routine_day_id, "routine_day_id") if body.routine_day_id else None
    gym_id = _parse_uuid(body.gym_id, "gym_id") if body.gym_id else None

    s = WorkoutLog(
        user_id=current_user.id,
        routine_day_id=routine_day_id,
        gym_id=gym_id,
        status=WorkoutStatus.IN_PROGRESS,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return SuccessResponse(data=_session_to_dto(s))


# ── POST /sessions/{id}/sets ──────────────────────────────────────────────────
@router.post(
    "/{session_id}/sets",
    response_model=SuccessResponse[WorkoutSetItem],
    status_code=201,
    summary="세트 기록",
)
async def log_set(
    session_id: str,
    body: LogSetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_my_session(session_id, current_user, db)
    if s.status == WorkoutStatus.COMPLETED:
        raise ConflictError(message="이미 종료된 세션에는 세트를 추가할 수 없습니다.")

    exercise_id = _parse_uuid(body.exercise_id, "exercise_id")
    rex_id = _parse_uuid(body.routine_exercise_id, "routine_exercise_id") if body.routine_exercise_id else None

    set_record = WorkoutLogSet(
        workout_log_id=s.id,
        exercise_id=exercise_id,
        routine_exercise_id=rex_id,
        set_number=body.set_number,
        weight_kg=body.weight_kg,
        reps=body.reps,
        rpe=body.rpe,
        is_completed=body.is_completed,
    )
    db.add(set_record)
    await db.commit()
    await db.refresh(set_record)

    ex_name = (await db.execute(select(Exercise.name).where(Exercise.id == exercise_id))).scalar_one_or_none()

    return SuccessResponse(
        data=WorkoutSetItem(
            set_id=str(set_record.id),
            exercise_id=str(set_record.exercise_id),
            exercise_name=ex_name,
            set_number=set_record.set_number,
            weight_kg=set_record.weight_kg,
            reps=set_record.reps,
            rpe=set_record.rpe,
            is_completed=set_record.is_completed,
            performed_at=set_record.performed_at,
        )
    )


# ── PATCH /sessions/{id}/finish ───────────────────────────────────────────────
@router.patch("/{session_id}/finish", response_model=SuccessResponse[SessionData], summary="세션 종료")
async def finish_session(
    session_id: str,
    body: FinishSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_my_session(session_id, current_user, db)
    if s.status == WorkoutStatus.COMPLETED:
        raise ConflictError(message="이미 종료된 세션입니다.")
    dt = body.finished_at or datetime.now(timezone.utc)
    s.finished_at = dt.replace(tzinfo=None)
    s.status = WorkoutStatus.COMPLETED
    await db.commit()
    await db.refresh(s)
    return SuccessResponse(data=_session_to_dto(s))


# ── GET /sessions?year=&month= ────────────────────────────────────────────────
@router.get("", response_model=SuccessResponse[SessionListData], summary="월별 세션 목록")
async def list_sessions(
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WorkoutLog).where(WorkoutLog.user_id == current_user.id)
    if year is not None and month is not None:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        stmt = stmt.where(WorkoutLog.started_at >= start, WorkoutLog.started_at < end)

    rows = (await db.execute(stmt.order_by(WorkoutLog.started_at.desc()))).scalars().all()
    return SuccessResponse(data=SessionListData(items=[_session_to_dto(s) for s in rows]))


# ── GET /sessions/stats ───────────────────────────────────────────────────────
@router.get("/stats", response_model=SuccessResponse[SessionStatsData], summary="세션 통계")
async def session_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total_sessions_q = await db.execute(select(func.count(WorkoutLog.id)).where(WorkoutLog.user_id == current_user.id))
    total_sessions = int(total_sessions_q.scalar() or 0)

    # 총 볼륨 = sum(weight_kg * reps) — null safe
    volume_q = await db.execute(
        select(func.coalesce(func.sum(WorkoutLogSet.weight_kg * WorkoutLogSet.reps), 0.0))
        .join(WorkoutLog, WorkoutLogSet.workout_log_id == WorkoutLog.id)
        .where(WorkoutLog.user_id == current_user.id, WorkoutLogSet.is_completed.is_(True))
    )
    total_volume = float(volume_q.scalar() or 0.0)

    # 총 분 = sum(finished_at - started_at) — completed만
    finished_rows = (
        await db.execute(
            select(WorkoutLog.started_at, WorkoutLog.finished_at).where(
                WorkoutLog.user_id == current_user.id,
                WorkoutLog.status == WorkoutStatus.COMPLETED,
                WorkoutLog.finished_at.is_not(None),
            )
        )
    ).all()
    total_minutes = sum(int((f - s).total_seconds() // 60) for s, f in finished_rows if f and s)

    # 연속 일수 — 최근 운동 날짜 기준
    streak_days = await _compute_streak(current_user.id, db)

    return SuccessResponse(
        data=SessionStatsData(
            total_sessions=total_sessions,
            total_volume_kg=round(total_volume, 2),
            total_minutes=total_minutes,
            streak_days=streak_days,
        )
    )


async def _compute_streak(user_id: uuid.UUID, db: AsyncSession) -> int:
    rows = (
        await db.execute(select(func.date(WorkoutLog.started_at)).where(WorkoutLog.user_id == user_id).distinct())
    ).all()
    dates = sorted({r[0] for r in rows}, reverse=True)
    if not dates:
        return 0
    today = datetime.now(timezone.utc).date()
    if dates[0] != today and dates[0] != today - timedelta(days=1):
        return 0
    streak = 1
    cursor = dates[0]
    for d in dates[1:]:
        if d == cursor - timedelta(days=1):
            streak += 1
            cursor = d
        else:
            break
    return streak


# ── GET /sessions/analysis/volume ─────────────────────────────────────────────
@router.get("/analysis/volume", response_model=SuccessResponse[VolumeAnalysisData], summary="볼륨 추이")
async def volume_analysis(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                func.date(WorkoutLog.started_at).label("d"),
                func.coalesce(func.sum(WorkoutLogSet.weight_kg * WorkoutLogSet.reps), 0.0).label("v"),
            )
            .join(WorkoutLogSet, WorkoutLogSet.workout_log_id == WorkoutLog.id)
            .where(
                WorkoutLog.user_id == current_user.id,
                WorkoutLog.started_at >= since,
                WorkoutLogSet.is_completed.is_(True),
            )
            .group_by("d")
            .order_by("d")
        )
    ).all()
    items = [
        VolumeAnalysisItem(date=d.isoformat() if isinstance(d, date) else str(d), volume_kg=float(v)) for d, v in rows
    ]
    return SuccessResponse(data=VolumeAnalysisData(items=items))


# ── GET /sessions/{id} ────────────────────────────────────────────────────────
@router.get("/{session_id}", response_model=SuccessResponse[SessionDetail], summary="세션 상세")
async def session_detail(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_my_session(session_id, current_user, db)
    sets_rows = (
        await db.execute(
            select(WorkoutLogSet, Exercise.name)
            .outerjoin(Exercise, WorkoutLogSet.exercise_id == Exercise.id)
            .where(WorkoutLogSet.workout_log_id == s.id)
            .order_by(WorkoutLogSet.performed_at)
        )
    ).all()
    set_dtos = [
        WorkoutSetItem(
            set_id=str(setrec.id),
            exercise_id=str(setrec.exercise_id),
            exercise_name=ex_name,
            set_number=setrec.set_number,
            weight_kg=setrec.weight_kg,
            reps=setrec.reps,
            rpe=setrec.rpe,
            is_completed=setrec.is_completed,
            performed_at=setrec.performed_at,
        )
        for setrec, ex_name in sets_rows
    ]
    total_volume = sum((s.weight_kg or 0) * s.reps for s in set_dtos if s.is_completed)
    return SuccessResponse(
        data=SessionDetail(
            session_id=str(s.id),
            routine_day_id=str(s.routine_day_id) if s.routine_day_id else None,
            gym_id=str(s.gym_id) if s.gym_id else None,
            started_at=s.started_at,
            finished_at=s.finished_at,
            status=s.status.value if s.status else "in_progress",
            sets=set_dtos,
            total_volume_kg=round(total_volume, 2),
        )
    )


# ── GET /sessions/{id}/rest-timer ─────────────────────────────────────────────
@router.get(
    "/{session_id}/rest-timer",
    response_model=SuccessResponse[RestTimerData],
    summary="권장 휴식 시간",
)
async def rest_timer(
    session_id: str,
    routine_exercise_id: str | None = Query(None),
    goal: str | None = Query(None, description="hypertrophy / strength / endurance / rehabilitation"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_my_session(session_id, current_user, db)

    # 1순위: 루틴 운동에 정의된 rest_seconds
    if routine_exercise_id:
        rex_id = _parse_uuid(routine_exercise_id, "routine_exercise_id")
        rex = (await db.execute(select(RoutineExercise).where(RoutineExercise.id == rex_id))).scalar_one_or_none()
        if rex is not None:
            return SuccessResponse(data=RestTimerData(rest_seconds=rex.rest_seconds, based_on="routine"))

    # 2순위: 목표별 디폴트
    defaults = {
        "hypertrophy": 90,
        "strength": 180,
        "endurance": 60,
        "rehabilitation": 60,
    }
    return SuccessResponse(
        data=RestTimerData(rest_seconds=defaults.get(goal or "hypertrophy", 90), based_on="goal_default")
    )
