"""세션(운동 로그) 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #29-36, #48.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_required_profile
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.limiter import rate_limit
from app.models import (
    Equipment,
    Exercise,
    ExerciseMuscle,
    Gym,
    MuscleGroup,
    Notification,
    NotificationType,
    RoutineDay,
    RoutineExercise,
    User,
    UserBodyMeasurement,
    UserExercise1RM,
    WorkoutLog,
    WorkoutLogSet,
    WorkoutRoutine,
    WorkoutStatus,
)
from app.schemas.common import SuccessResponse
from app.schemas.sessions import (
    ActiveSessionData,
    FinishSessionRequest,
    GymStatItem,
    LogSetRequest,
    MuscleVolumeData,
    MuscleVolumeItem,
    RecentSessionItem,
    RestTimerData,
    SessionCalendarData,
    SessionCalendarItem,
    SessionData,
    SessionDetail,
    SessionStartData,
    SessionStatsData,
    StartSessionRequest,
    VolumeAnalysisData,
    VolumeAnalysisItem,
    WorkoutSetItem,
)
from app.services import po, po_rag

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# 한국 표준시 오프셋 — started_at 은 UTC 나이브로 저장되므로 KST 날짜 계산 시 보정
_KST = timedelta(hours=9)

_REST_GOAL_DEFAULTS: dict[str, tuple[int, int, int]] = {
    "hypertrophy": (90, 60, 120),
    "strength": (180, 120, 300),
    "endurance": (60, 30, 60),
    "rehabilitation": (60, 30, 90),
}

_BODY_PART_KO: dict[str, str] = {
    "chest": "가슴",
    "back": "등",
    "shoulder": "어깨",
    "shoulders": "어깨",
    "legs": "하체",
    "arms": "팔",
    "abs": "복근",
}


def _fmt_seconds(s: int) -> str:
    if s < 60:
        return f"{s}초"
    m, r = divmod(s, 60)
    return f"{m}분" if r == 0 else f"{m}분 {r}초"


def _parse_uuid(v: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise ValidationError(message=f"잘못된 {name} 형식입니다.") from e


def _strip_tz(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _session_to_dto(
    s: WorkoutLog,
    routine_name: str | None = None,
) -> SessionData:
    duration_minutes: int | None = None
    if s.finished_at and s.started_at:
        duration_minutes = max(
            0,
            int((_strip_tz(s.finished_at) - _strip_tz(s.started_at)).total_seconds() // 60),
        )
    return SessionData(
        session_id=str(s.id),
        routine_day_id=str(s.routine_day_id) if s.routine_day_id else None,
        gym_id=str(s.gym_id) if s.gym_id else None,
        started_at=s.started_at,
        finished_at=s.finished_at,
        status=str(s.status) if s.status else "in_progress",
        routine_name=routine_name,
        duration_minutes=duration_minutes,
    )


async def _get_my_session(session_id: str, user: User, db: AsyncSession) -> WorkoutLog:
    sid = _parse_uuid(session_id, "session_id")
    s = (
        await db.execute(
            select(WorkoutLog).where(
                WorkoutLog.id == sid,
                WorkoutLog.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise NotFoundError(message="세션을 찾을 수 없습니다.")
    return s


async def _compute_streak(user_id: uuid.UUID, db: AsyncSession) -> int:
    # started_at은 UTC 저장 → KST 날짜 기준으로 연속 운동 계산
    rows = (
        await db.execute(
            select(func.date(WorkoutLog.started_at + text("interval '9 hours'")).label("kst_date"))
            .where(WorkoutLog.user_id == user_id)
            .distinct()
        )
    ).all()
    dates = sorted({r[0] for r in rows}, reverse=True)
    if not dates:
        return 0

    today = (datetime.now(timezone.utc) + _KST).date()  # KST 오늘 날짜
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


# ── POST /sessions ────────────────────────────────────────────────────────────
@router.post("", response_model=SuccessResponse[SessionStartData], status_code=201, summary="세션 시작")
@rate_limit("60/minute")
async def start_session(
    request: Request,
    body: StartSessionRequest,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    session_routine_day_id = None
    session_routine_id: str | None = None
    session_routine_name: str | None = None
    session_gym_id: uuid.UUID | None = None

    # body.gym_id 명시 시 우선 사용
    if body.gym_id:
        session_gym_id = _parse_uuid(body.gym_id, "gym_id")

    if body.routine_id:
        routine_id = _parse_uuid(body.routine_id, "routine_id")
        routine = (
            await db.execute(
                select(WorkoutRoutine).where(
                    WorkoutRoutine.id == routine_id,
                    WorkoutRoutine.user_id == current_user.id,
                    WorkoutRoutine.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if routine is None:
            raise NotFoundError(message="루틴을 찾을 수 없습니다.")

        session_routine_id = str(routine_id)
        session_routine_name = routine.name

        # gym_id 미지정 시 루틴의 gym_id 자동 복사 (D-M9)
        if session_gym_id is None and routine.gym_id:
            session_gym_id = routine.gym_id
        # routine_day_id가 명시적으로 전달된 경우 우선 사용 (멀티 day 루틴 대응)
        # 그렇지 않으면 첫 번째 day 자동 선택
        if body.routine_day_id:
            session_routine_day_id = _parse_uuid(body.routine_day_id, "routine_day_id")
        else:
            first_day = (
                await db.execute(
                    select(RoutineDay)
                    .where(RoutineDay.routine_id == routine_id)
                    .order_by(RoutineDay.day_number)
                    .limit(1)
                )
            ).scalar_one_or_none()
            session_routine_day_id = first_day.id if first_day else None
    elif body.routine_day_id:
        session_routine_day_id = _parse_uuid(body.routine_day_id, "routine_day_id")

    s = WorkoutLog(
        user_id=current_user.id,
        routine_day_id=session_routine_day_id,
        gym_id=session_gym_id,
        status=WorkoutStatus.IN_PROGRESS,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)

    return SuccessResponse(
        data=SessionStartData(
            session_id=str(s.id),
            routine_id=session_routine_id,
            routine_name=session_routine_name,
            gym_id=str(session_gym_id) if session_gym_id else None,
            started_at=s.started_at,
        )
    )


# ── POST /sessions/{id}/sets ──────────────────────────────────────────────────
@router.post(
    "/{session_id}/sets",
    response_model=SuccessResponse[WorkoutSetItem],
    status_code=201,
    summary="세트 기록",
)
@rate_limit("60/minute")
async def log_set(
    request: Request,
    session_id: str,
    body: LogSetRequest,
    current_user: User = Depends(get_required_profile),
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


async def _check_and_create_po_notifications(
    session: WorkoutLog,
    user: User,
    db: AsyncSession,
) -> None:
    if not session.routine_day_id:
        return

    goal_row = (
        await db.execute(
            select(WorkoutRoutine.fitness_goals)
            .join(RoutineDay, RoutineDay.routine_id == WorkoutRoutine.id)
            .where(RoutineDay.id == session.routine_day_id)
        )
    ).scalar_one_or_none()

    if not goal_row or not isinstance(goal_row, list):
        return
    # TODO(D-MX): 복수 목표 시 PO 계산 기준 미결정 → 현재는 첫 번째 목표만 사용
    goal = goal_row[0]

    # 이 세션의 routine_exercise별 (max_reps, max_weight, set_count) 조회
    set_rows = (
        await db.execute(
            select(
                WorkoutLogSet.routine_exercise_id,
                func.max(WorkoutLogSet.reps).label("max_reps"),
                func.max(WorkoutLogSet.weight_kg).label("max_weight"),
                func.count(WorkoutLogSet.id).label("set_count"),
            )
            .where(
                WorkoutLogSet.workout_log_id == session.id,
                WorkoutLogSet.routine_exercise_id.is_not(None),
                WorkoutLogSet.is_completed.is_(True),
            )
            .group_by(WorkoutLogSet.routine_exercise_id)
        )
    ).all()

    if not set_rows:
        return

    rex_ids = [row[0] for row in set_rows]

    # ── 직전 세션의 max_reps — IN 쿼리 일괄 조회 (연속 2세션 조건) ──────────────
    # 역대 MAX가 아닌 가장 최근 완료 세션 1개의 reps를 가져와야 "연속 2세션" 조건이 됨
    latest_session_subq = (
        select(
            WorkoutLogSet.routine_exercise_id,
            func.max(WorkoutLog.finished_at).label("latest_finished"),
        )
        .join(WorkoutLog, WorkoutLogSet.workout_log_id == WorkoutLog.id)
        .where(
            WorkoutLogSet.routine_exercise_id.in_(rex_ids),
            WorkoutLog.user_id == user.id,
            WorkoutLog.id != session.id,
            WorkoutLog.status == WorkoutStatus.COMPLETED,
            WorkoutLogSet.is_completed.is_(True),
        )
        .group_by(WorkoutLogSet.routine_exercise_id)
        .subquery()
    )
    prev_reps_rows = (
        await db.execute(
            select(
                WorkoutLogSet.routine_exercise_id,
                func.max(WorkoutLogSet.reps).label("max_reps"),
            )
            .join(WorkoutLog, WorkoutLogSet.workout_log_id == WorkoutLog.id)
            .join(
                latest_session_subq,
                (WorkoutLogSet.routine_exercise_id == latest_session_subq.c.routine_exercise_id)
                & (WorkoutLog.finished_at == latest_session_subq.c.latest_finished),
            )
            .where(
                WorkoutLog.user_id == user.id,
                WorkoutLog.status == WorkoutStatus.COMPLETED,
                WorkoutLogSet.is_completed.is_(True),
            )
            .group_by(WorkoutLogSet.routine_exercise_id)
        )
    ).all()
    prev_reps_map: dict[str, int] = {str(rex_id): int(max_reps) for rex_id, max_reps in prev_reps_rows}

    # ── RoutineExercise / Exercise / Equipment — 일괄 조회 ───────────────────
    rex_records = (await db.execute(select(RoutineExercise).where(RoutineExercise.id.in_(rex_ids)))).scalars().all()
    rex_map = {rex.id: rex for rex in rex_records}

    exercise_ids = list({rex.exercise_id for rex in rex_records})
    # id → (name, load_mode) 로 구조 변경: load_mode를 같은 쿼리에서 가져와 N+1 방지
    ex_meta_map: dict = {
        r.id: (r.name, r.load_mode)
        for r in (
            await db.execute(
                select(Exercise.id, Exercise.name, Exercise.load_mode).where(Exercise.id.in_(exercise_ids))
            )
        ).all()
    }

    equip_ids = list({rex.equipment_id for rex in rex_records if rex.equipment_id})
    equip_map: dict = {}
    if equip_ids:
        equip_map = {
            e.id: e for e in (await db.execute(select(Equipment).where(Equipment.id.in_(equip_ids)))).scalars().all()
        }

    # ── PO 체크 및 알림 생성 ─────────────────────────────────────────────────
    new_notifications: list[Notification] = []

    for rex_id, cur_max_reps, cur_max_weight, set_count in set_rows:
        prev_max_reps = prev_reps_map.get(str(rex_id))
        if prev_max_reps is None or cur_max_reps is None:
            continue
        if not po.check_po_trigger([prev_max_reps, int(cur_max_reps)], goal):
            continue

        rex = rex_map.get(rex_id)
        if rex is None:
            continue

        name, lm = ex_meta_map.get(rex.exercise_id, ("운동", None))
        ex_name = str(name)

        # cardio는 부하 개념이 없어 PO 대상 제외
        if lm == "cardio":
            continue

        # load_mode를 1차 소스로 사용.
        # load_mode가 None인 레거시 데이터는 'barbell' 안전망(재시드 후 실질 영향 0).
        max_stack = None
        if lm in ("cable", "machine") and rex.equipment_id:
            equip = equip_map.get(rex.equipment_id)
            if equip:
                category = lm
                max_stack = equip.max_stack
            else:
                category = lm or "barbell"
        else:
            category = lm or "barbell"
            if rex.equipment_id:
                equip = equip_map.get(rex.equipment_id)
                if equip:
                    max_stack = equip.max_stack

        user_1rm_row = (
            await db.execute(
                select(UserExercise1RM.weight_kg)
                .where(
                    UserExercise1RM.user_id == user.id,
                    UserExercise1RM.exercise_id == rex.exercise_id,
                )
                .order_by(UserExercise1RM.estimated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        user_1rm_kg = float(user_1rm_row) if user_1rm_row is not None else None
        increment_override = await po_rag.rag_po_increment(goal, category, user_1rm_kg)

        result = po.calculate_increase(
            category=category,
            goal=goal,
            current_weight=float(cur_max_weight or 0),
            current_sets=rex.sets or int(set_count),
            max_stack=max_stack,
            increment_override=increment_override,
        )

        # 루틴 중량/세트 즉시 반영 — 다음 루틴 접속 시 업데이트된 값이 보임
        rex.weight_kg = result["new_weight"]
        rex.sets = result["new_sets"]

        if result["overflow"] and result["message"]:
            new_notifications.append(
                Notification(
                    user_id=user.id,
                    type=NotificationType.PO_SUGGESTION,
                    title="더 무거운 기구를 사용해보세요",
                    body=f"{ex_name}: {result['message']}",
                    data_json={
                        "routine_exercise_id": str(rex_id),
                        "exercise_id": str(rex.exercise_id),
                    },
                )
            )
        else:
            new_notifications.append(
                Notification(
                    user_id=user.id,
                    type=NotificationType.PO_SUGGESTION,
                    title="중량 증가를 권장해요",
                    body=f"{ex_name} {cur_max_weight}kg → {result['new_weight']}kg으로 올려보세요",
                    data_json={
                        "routine_exercise_id": str(rex_id),
                        "exercise_id": str(rex.exercise_id),
                        "current_weight": float(cur_max_weight or 0),
                        "suggested_weight": result["new_weight"],
                    },
                )
            )

    if new_notifications:
        db.add_all(new_notifications)
        # 알림 생성은 세션 완료와 별도 트랜잭션으로 분리 — 알림 실패 시에도 세션은 이미 완료 상태
        await db.commit()
        logger.info("PO notifications created: %d for user %s", len(new_notifications), user.id)


# ── PATCH /sessions/{id}/finish ───────────────────────────────────────────────
@router.patch("/{session_id}/finish", response_model=SuccessResponse[SessionData], summary="세션 종료")
@rate_limit("60/minute")
async def finish_session(
    request: Request,
    session_id: str,
    body: FinishSessionRequest,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_my_session(session_id, current_user, db)
    if s.status == WorkoutStatus.COMPLETED:
        raise ConflictError(message="이미 종료된 세션입니다.")

    dt = body.finished_at or datetime.now(timezone.utc)
    candidate = dt.replace(tzinfo=None)
    # finished_at이 started_at보다 작으면 앱의 타임존 파싱 오류 — 서버 시간으로 대체
    if s.started_at and candidate <= _strip_tz(s.started_at):
        candidate = datetime.now(timezone.utc).replace(tzinfo=None)
    s.finished_at = candidate
    s.status = WorkoutStatus.COMPLETED
    await db.commit()
    await db.refresh(s)

    total_sets = int(
        (
            await db.execute(select(func.count(WorkoutLogSet.id)).where(WorkoutLogSet.workout_log_id == s.id))
        ).scalar_one()
    )

    completed_exercises = int(
        (
            await db.execute(
                select(func.count(func.distinct(WorkoutLogSet.exercise_id))).where(
                    WorkoutLogSet.workout_log_id == s.id,
                    WorkoutLogSet.is_completed.is_(True),
                )
            )
        ).scalar_one()
    )

    latest_measurement = (
        await db.execute(
            select(UserBodyMeasurement)
            .where(UserBodyMeasurement.user_id == current_user.id)
            .order_by(UserBodyMeasurement.measured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    body_weight = latest_measurement.weight_kg if latest_measurement else 70.0

    dto = _session_to_dto(s)
    dto.total_sets = total_sets
    dto.completed_exercises = completed_exercises
    dto.total_calories = round(5.0 * body_weight * dto.duration_minutes / 60) if dto.duration_minutes else None

    await _check_and_create_po_notifications(s, current_user, db)

    return SuccessResponse(data=dto)


# ── GET /sessions?year=&month= ────────────────────────────────────────────────
@router.get("", response_model=SuccessResponse[SessionCalendarData], summary="월별 세션 목록")
@rate_limit("60/minute")
async def list_sessions(
    request: Request,
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    now_kst = datetime.now(timezone.utc) + _KST
    q_year = year or now_kst.year
    q_month = month or now_kst.month

    # KST 월 경계를 UTC 나이브 datetime 으로 변환
    # 예) KST 6월 1일 00:00 = UTC 5월 31일 15:00 → -9h 보정
    kst_start = datetime(q_year, q_month, 1)
    kst_end = datetime(q_year + 1, 1, 1) if q_month == 12 else datetime(q_year, q_month + 1, 1)
    start = kst_start - _KST
    end = kst_end - _KST

    rows = (
        (
            await db.execute(
                select(WorkoutLog)
                .where(
                    WorkoutLog.user_id == current_user.id,
                    WorkoutLog.started_at >= start,
                    WorkoutLog.started_at < end,
                )
                .order_by(WorkoutLog.started_at.desc())
            )
        )
        .scalars()
        .all()
    )

    day_ids = [r.routine_day_id for r in rows if r.routine_day_id]
    # day_id → (routine_id, routine_name, fitness_goals, target_muscle_group_ids)
    routine_info_by_day: dict[str, tuple[str, str, list[str], list[str]]] = {}

    if day_ids:
        name_rows = (
            await db.execute(
                select(
                    RoutineDay.id,
                    WorkoutRoutine.id,
                    WorkoutRoutine.name,
                    WorkoutRoutine.fitness_goals,
                    WorkoutRoutine.target_muscle_group_ids,
                )
                .join(WorkoutRoutine, RoutineDay.routine_id == WorkoutRoutine.id)
                .where(RoutineDay.id.in_(day_ids))
            )
        ).all()
        routine_info_by_day = {
            str(did): (
                str(rid),
                rname,
                goals or [],
                [_BODY_PART_KO.get(m, m) for m in (muscles or [])],
            )
            for did, rid, rname, goals, muscles in name_rows
        }

    gym_ids = [r.gym_id for r in rows if r.gym_id]
    gym_name_by_id: dict[str, str] = {}
    if gym_ids:
        gym_rows_q = (await db.execute(select(Gym.id, Gym.name).where(Gym.id.in_(gym_ids)))).all()
        gym_name_by_id = {str(gid): gname for gid, gname in gym_rows_q}

    # 세션별 총 중량 / 총 세트 집계 (완료된 세트만)
    session_ids = [r.id for r in rows]
    session_agg: dict[str, tuple[float, int, float]] = {}
    if session_ids:
        agg_rows = (
            await db.execute(
                select(
                    WorkoutLogSet.workout_log_id,
                    func.coalesce(func.sum(WorkoutLogSet.weight_kg * WorkoutLogSet.reps), 0.0).label("volume"),
                    func.count(WorkoutLogSet.id).label("sets"),
                    func.coalesce(func.sum(WorkoutLogSet.weight_kg), 0.0).label("weight"),
                )
                .where(
                    WorkoutLogSet.workout_log_id.in_(session_ids),
                    WorkoutLogSet.is_completed.is_(True),
                )
                .group_by(WorkoutLogSet.workout_log_id)
            )
        ).all()
        session_agg = {str(sid): (float(vol), int(sets), float(weight)) for sid, vol, sets, weight in agg_rows}

    _no_info: tuple[str | None, str | None, list[str], list[str]] = (None, None, [], [])

    # 완료된 세트가 있는 세션만 표시 + 같은 날 같은 루틴은 1건으로 합산
    merged: dict[str, SessionCalendarItem] = {}
    for s in rows:
        if str(s.id) not in session_agg:
            continue  # 세트 기록이 없는 빈 세션 제외

        kst_date = (s.started_at + _KST).date().isoformat()
        info = routine_info_by_day.get(str(s.routine_day_id), _no_info) if s.routine_day_id else _no_info
        routine_id_val = info[0]
        # routine_id가 없는 자유 운동 세션은 세션별로 독립 표시 (합산 대상 아님)
        key = f"{kst_date}_{routine_id_val}" if routine_id_val else f"{kst_date}_{s.id}"

        vol, sets, weight = session_agg.get(str(s.id), (0.0, 0, 0.0))
        # 완료된 세션만 시간 집계 — IN_PROGRESS 세션은 now - started_at이 계속 늘어나므로 0 처리
        duration = (
            max(0, int((_strip_tz(s.finished_at) - _strip_tz(s.started_at)).total_seconds() // 60))
            if s.finished_at and s.started_at and s.status == WorkoutStatus.COMPLETED
            else 0
        )

        if key not in merged:
            merged[key] = SessionCalendarItem(
                date=kst_date,
                session_id=str(s.id),
                routine_id=routine_id_val,
                routine_name=info[1],
                fitness_goals=info[2],
                target_muscle_names=info[3],
                duration_minutes=duration or 0,
                gym_name=gym_name_by_id.get(str(s.gym_id)) if s.gym_id else None,
                total_volume_kg=vol,
                total_sets=sets,
                total_weight_kg=weight,
            )
        else:
            item = merged[key]
            item.total_volume_kg += vol
            item.total_sets += sets
            item.total_weight_kg += weight
            if duration is not None:
                item.duration_minutes = (item.duration_minutes or 0) + duration

    records = list(merged.values())

    return SuccessResponse(
        data=SessionCalendarData(
            year=q_year,
            month=q_month,
            records=records,
            total_session_count=len(records),
        )
    )


# ── GET /sessions/stats ───────────────────────────────────────────────────────
@router.get("/stats", response_model=SuccessResponse[SessionStatsData], summary="세션 통계")
@rate_limit("60/minute")
async def session_stats(
    request: Request,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    # 총 세션 수 — 완료된 세트가 있는 세션만, 같은 날 같은 루틴은 1개로 카운트
    all_session_rows = (
        await db.execute(
            select(WorkoutLog.started_at, WorkoutLog.routine_day_id)
            .join(WorkoutLogSet, WorkoutLogSet.workout_log_id == WorkoutLog.id)
            .where(
                WorkoutLog.user_id == current_user.id,
                WorkoutLogSet.is_completed.is_(True),
            )
            .distinct()
        )
    ).all()
    seen_session_keys: set[str] = set()
    for started_at, routine_day_id in all_session_rows:
        kst_date = (started_at + _KST).date().isoformat()
        seen_session_keys.add(f"{kst_date}_{routine_day_id}")
    total_sessions = len(seen_session_keys)

    # 총 볼륨 (weight × reps)
    total_volume = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(WorkoutLogSet.weight_kg * WorkoutLogSet.reps), 0.0))
                .join(WorkoutLog, WorkoutLogSet.workout_log_id == WorkoutLog.id)
                .where(
                    WorkoutLog.user_id == current_user.id,
                    WorkoutLogSet.is_completed.is_(True),
                )
            )
        ).scalar()
        or 0.0
    )

    # 총 중량 (세트 무게 단순 합산 — weight × reps 아님)
    total_weight = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(WorkoutLogSet.weight_kg), 0.0))
                .join(WorkoutLog, WorkoutLogSet.workout_log_id == WorkoutLog.id)
                .where(
                    WorkoutLog.user_id == current_user.id,
                    WorkoutLogSet.is_completed.is_(True),
                )
            )
        ).scalar()
        or 0.0
    )

    # 총 세트 수
    total_sets = int(
        (
            await db.execute(
                select(func.count(WorkoutLogSet.id))
                .join(WorkoutLog, WorkoutLogSet.workout_log_id == WorkoutLog.id)
                .where(
                    WorkoutLog.user_id == current_user.id,
                    WorkoutLogSet.is_completed.is_(True),
                )
            )
        ).scalar()
        or 0
    )

    # 총 운동 시간 (완료된 세션만)
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

    # 총 칼로리 (최근 체중 기준, MET 5.0 공식)
    latest_measurement = (
        await db.execute(
            select(UserBodyMeasurement)
            .where(UserBodyMeasurement.user_id == current_user.id)
            .order_by(UserBodyMeasurement.measured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    body_weight_kg = float(latest_measurement.weight_kg) if latest_measurement else 70.0
    total_calories_kcal = round(5.0 * body_weight_kg * total_minutes / 60)

    # 주간 세션 수 (최근 7일) — 완료된 세트가 있는 세션만, 같은 날 같은 루틴은 1개로 카운트
    # KST 기준 7일 전 자정 → UTC 변환 (list_sessions의 KST 날짜 경계 정책과 일관성 유지)
    today_kst_date = (datetime.now(timezone.utc) + _KST).date()
    week_ago_kst_date = today_kst_date - timedelta(days=7)
    week_ago = datetime(week_ago_kst_date.year, week_ago_kst_date.month, week_ago_kst_date.day) - _KST
    weekly_rows = (
        await db.execute(
            select(WorkoutLog.started_at, WorkoutLog.routine_day_id)
            .join(WorkoutLogSet, WorkoutLogSet.workout_log_id == WorkoutLog.id)
            .where(
                WorkoutLog.user_id == current_user.id,
                WorkoutLog.started_at >= week_ago,
                WorkoutLogSet.is_completed.is_(True),
            )
            .distinct()
        )
    ).all()
    seen_weekly_keys: set[str] = set()
    for started_at, routine_day_id in weekly_rows:
        kst_date = (started_at + _KST).date().isoformat()
        seen_weekly_keys.add(f"{kst_date}_{routine_day_id}")
    weekly_session_count = len(seen_weekly_keys)

    # 최근 완료 세션
    recent_row = (
        await db.execute(
            select(WorkoutLog)
            .where(
                WorkoutLog.user_id == current_user.id,
                WorkoutLog.status == WorkoutStatus.COMPLETED,
            )
            .order_by(WorkoutLog.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    recent_session: RecentSessionItem | None = None

    if recent_row:
        routine_name: str | None = None
        if recent_row.routine_day_id:
            routine_name = (
                await db.execute(
                    select(WorkoutRoutine.name)
                    .join(RoutineDay, RoutineDay.routine_id == WorkoutRoutine.id)
                    .where(RoutineDay.id == recent_row.routine_day_id)
                )
            ).scalar_one_or_none()

        recent_session = RecentSessionItem(
            session_id=str(recent_row.id),
            routine_name=routine_name,
            date=recent_row.started_at.date().isoformat(),
        )

    streak_days = await _compute_streak(current_user.id, db)

    # gym별 집계 (D-M9)
    gym_rows = (
        await db.execute(
            select(
                Gym.id,
                Gym.name,
                func.count(WorkoutLog.id).label("session_count"),
                func.coalesce(func.sum(WorkoutLogSet.weight_kg * WorkoutLogSet.reps), 0.0).label("volume"),
            )
            .join(WorkoutLog, WorkoutLog.gym_id == Gym.id)
            .outerjoin(
                WorkoutLogSet,
                (WorkoutLogSet.workout_log_id == WorkoutLog.id) & WorkoutLogSet.is_completed.is_(True),
            )
            .where(WorkoutLog.user_id == current_user.id)
            .group_by(Gym.id, Gym.name)
            .order_by(func.count(WorkoutLog.id).desc())
        )
    ).all()

    by_gym = [
        GymStatItem(
            gym_id=str(gid),
            gym_name=gname,
            session_count=int(cnt),
            total_volume_kg=round(float(vol), 2),
        )
        for gid, gname, cnt, vol in gym_rows
    ]

    return SuccessResponse(
        data=SessionStatsData(
            total_sessions=total_sessions,
            total_volume_kg=round(total_volume, 2),
            total_weight_kg=round(total_weight, 2),
            total_duration_minutes=total_minutes,
            total_sets=total_sets,
            weekly_session_count=weekly_session_count,
            streak_days=streak_days,
            total_calories_kcal=total_calories_kcal,
            recent_session=recent_session,
            by_gym=by_gym,
        )
    )


# ── GET /sessions/analysis/volume ─────────────────────────────────────────────
@router.get("/analysis/volume", response_model=SuccessResponse[VolumeAnalysisData], summary="볼륨 추이")
@rate_limit("60/minute")
async def volume_analysis(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    # WorkoutLog.started_at은 timezone-naive로 저장되므로 replace(tzinfo=None) 필수
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
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
        VolumeAnalysisItem(
            date=d.isoformat() if isinstance(d, date) else str(d),
            volume_kg=float(v),
        )
        for d, v in rows
    ]

    return SuccessResponse(data=VolumeAnalysisData(items=items))


# ── GET /sessions/analysis/muscle-volume ─────────────────────────────────────
# 근육 부위별 주간/월간 볼륨 조회 + 근비대 최적 범위 비교
# 키는 muscle_groups.name_ko 값과 정확히 일치해야 함 (seed: 20260525_seed_muscle_groups_exercises.py)
_OPTIMAL_RANGES: dict[str, tuple[float, float]] = {
    "대흉근": (4000, 6000),  # pectoralis_major  ← 벤치프레스
    "광배근": (4000, 6000),  # latissimus_dorsi  ← 바벨로우, 풀업
    "능형근": (3000, 5000),  # rhomboids         ← 바벨로우
    "승모근": (2000, 4000),  # trapezius
    "전면 삼각근": (2000, 4000),  # anterior_deltoid  ← 오버헤드프레스
    "측면 삼각근": (2000, 4000),  # lateral_deltoid
    "후면 삼각근": (2000, 4000),  # posterior_deltoid
    "이두근": (2000, 4000),  # biceps_brachii
    "삼두근": (2000, 4000),  # triceps_brachii
    "전완근": (1000, 3000),  # forearms
    "복직근": (2000, 4000),  # rectus_abdominis  ← 플랭크
    "대퇴사두근": (6000, 10000),  # quadriceps        ← 백 스쿼트
    "햄스트링": (4000, 8000),  # hamstrings
    "대둔근": (4000, 8000),  # gluteus_maximus
    "종아리": (2000, 4000),  # calves
}


@router.get(
    "/analysis/muscle-volume",
    response_model=SuccessResponse[MuscleVolumeData],
    summary="근육 부위별 볼륨 분석",
)
@rate_limit("60/minute")
async def muscle_volume_analysis(
    request: Request,
    period: str = Query("WEEK", pattern="^(WEEK|MONTH)$"),
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    days = 7 if period == "WEEK" else 30
    # WorkoutLog.started_at은 timezone-naive로 저장되므로 replace(tzinfo=None) 필수
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    rows = (
        await db.execute(
            select(
                MuscleGroup.name_ko,
                func.coalesce(func.sum(WorkoutLogSet.weight_kg * WorkoutLogSet.reps), 0.0).label("volume"),
            )
            .join(ExerciseMuscle, ExerciseMuscle.muscle_group_id == MuscleGroup.id)
            .join(WorkoutLogSet, WorkoutLogSet.exercise_id == ExerciseMuscle.exercise_id)
            .join(WorkoutLog, WorkoutLog.id == WorkoutLogSet.workout_log_id)
            .where(
                WorkoutLog.user_id == current_user.id,
                WorkoutLog.started_at >= since,
                WorkoutLogSet.is_completed.is_(True),
            )
            .group_by(MuscleGroup.name_ko)
            .order_by(MuscleGroup.name_ko)
        )
    ).all()

    volume_map = {name_ko: float(vol) for name_ko, vol in rows}

    items: list[MuscleVolumeItem] = []

    for muscle, (opt_min, opt_max) in _OPTIMAL_RANGES.items():
        vol = volume_map.get(muscle, 0.0)

        if opt_min <= vol <= opt_max:
            status = "OPTIMAL"
        elif vol < opt_min:
            status = "LOW"
        else:
            status = "HIGH"

        items.append(
            MuscleVolumeItem(
                muscle=muscle,
                weekly_volume=vol,
                optimal_min=opt_min,
                optimal_max=opt_max,
                status=status,
            )
        )

    # AI 코치 멘트 생성 (LLM 없이 룰 기반)
    low_muscles = [i.muscle for i in items if i.status == "LOW" and i.weekly_volume > 0]
    optimal_muscles = [i.muscle for i in items if i.status == "OPTIMAL"]
    high_muscles = [i.muscle for i in items if i.status == "HIGH"]

    if not any(i.weekly_volume > 0 for i in items):
        ai_coach_message = "아직 운동 기록이 없습니다. 첫 운동을 시작해보세요!"
    elif high_muscles:
        ai_coach_message = f"{', '.join(high_muscles)} 볼륨이 최적 범위를 초과했습니다. 충분한 회복을 취하세요."
    elif low_muscles:
        ai_coach_message = f"{', '.join(low_muscles[:2])} 볼륨을 늘려보세요. 균형 잡힌 훈련이 중요합니다!"
    elif optimal_muscles:
        ai_coach_message = f"훌륭합니다! {', '.join(optimal_muscles[:2])} 등 볼륨이 최적 범위에 도달했습니다."
    else:
        ai_coach_message = "운동 기록을 쌓아가며 근육별 볼륨을 최적 범위로 맞춰나가세요!"

    return SuccessResponse(
        data=MuscleVolumeData(
            period=period,
            volume_by_muscle=items,
            ai_coach_message=ai_coach_message,
        )
    )


# ── GET /sessions/active ─────────────────────────────────────────────────────
# NOTE: /active must precede /{session_id} — FastAPI matches routes in
# declaration order; placing it after would capture "active" as session_id.
@router.get(
    "/active",
    response_model=SuccessResponse[ActiveSessionData | None],
    summary="진행 중인 세션 조회",
)
@rate_limit("60/minute")
async def get_active_session(
    request: Request,
    routine_id: str | None = Query(None, description="루틴 ID — 지정 시 해당 루틴의 진행 중 세션만 반환"),
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(WorkoutLog, RoutineDay.routine_id)
        .outerjoin(RoutineDay, WorkoutLog.routine_day_id == RoutineDay.id)
        .where(
            WorkoutLog.user_id == current_user.id,
            WorkoutLog.status == WorkoutStatus.IN_PROGRESS,
        )
        .order_by(WorkoutLog.started_at.desc())
        .limit(1)
    )

    if routine_id:
        routine_uuid = _parse_uuid(routine_id, "routine_id")
        stmt = stmt.where(RoutineDay.routine_id == routine_uuid)

    row = (await db.execute(stmt)).first()
    if row is None:
        return SuccessResponse(data=None)

    s, resolved_routine_id = row
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    elapsed = max(0, int((now - _strip_tz(s.started_at)).total_seconds()))

    return SuccessResponse(
        data=ActiveSessionData(
            session_id=str(s.id),
            routine_id=str(resolved_routine_id) if resolved_routine_id else None,
            routine_day_id=str(s.routine_day_id) if s.routine_day_id else None,
            gym_id=str(s.gym_id) if s.gym_id else None,
            started_at=s.started_at,
            elapsed_seconds=elapsed,
        )
    )


# ── GET /sessions/{id} ────────────────────────────────────────────────────────
@router.get("/{session_id}", response_model=SuccessResponse[SessionDetail], summary="세션 상세")
@rate_limit("60/minute")
async def session_detail(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_required_profile),
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

    total_volume = sum((ws.weight_kg or 0) * ws.reps for ws in set_dtos if ws.is_completed)

    routine_name: str | None = None

    if s.routine_day_id:
        routine_name = (
            await db.execute(
                select(WorkoutRoutine.name)
                .join(RoutineDay, RoutineDay.routine_id == WorkoutRoutine.id)
                .where(RoutineDay.id == s.routine_day_id)
            )
        ).scalar_one_or_none()

    return SuccessResponse(
        data=SessionDetail(
            session_id=str(s.id),
            routine_day_id=str(s.routine_day_id) if s.routine_day_id else None,
            gym_id=str(s.gym_id) if s.gym_id else None,
            started_at=s.started_at,
            finished_at=s.finished_at,
            status=str(s.status) if s.status else "in_progress",
            routine_name=routine_name,
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
@rate_limit("60/minute")
async def rest_timer(
    request: Request,
    session_id: str,
    routine_exercise_id: str | None = Query(None),
    goal: str | None = Query(None, description="hypertrophy / strength / endurance / rehabilitation"),
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    await _get_my_session(session_id, current_user, db)

    if routine_exercise_id:
        rex_id = _parse_uuid(routine_exercise_id, "routine_exercise_id")
        rex = (await db.execute(select(RoutineExercise).where(RoutineExercise.id == rex_id))).scalar_one_or_none()

        if rex is not None:
            rec = rex.rest_seconds
            mn = max(30, rec - 30)
            mx = rec + 30
            return SuccessResponse(
                data=RestTimerData(
                    rest_seconds=rec,
                    min_rest_seconds=mn,
                    max_rest_seconds=mx,
                    message=f"권장 휴식: {_fmt_seconds(mn)}~{_fmt_seconds(mx)}",
                    based_on="routine",
                )
            )

    rec, mn, mx = _REST_GOAL_DEFAULTS.get(goal or "hypertrophy", _REST_GOAL_DEFAULTS["hypertrophy"])
    return SuccessResponse(
        data=RestTimerData(
            rest_seconds=rec,
            min_rest_seconds=mn,
            max_rest_seconds=mx,
            message=f"권장 휴식: {_fmt_seconds(mn)}~{_fmt_seconds(mx)}",
            based_on="goal_default",
        )
    )
