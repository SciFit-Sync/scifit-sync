"""홈 대시보드 엔드포인트 (#29 GET /home)."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models import (
    Notification,
    RoutineDay,
    RoutineStatus,
    User,
    WorkoutLog,
    WorkoutLogSet,
    WorkoutRoutine,
)
from app.schemas.common import SuccessResponse
from app.schemas.notifications import HomeData, HomeRoutineSummary, NotificationItem

logger = logging.getLogger(__name__)

router = APIRouter(tags=["home"])


@router.get("/home", response_model=SuccessResponse[HomeData], summary="홈 대시보드")
async def home(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 1) 최근 활성 루틴
    active_routine = (
        await db.execute(
            select(WorkoutRoutine)
            .where(
                WorkoutRoutine.user_id == current_user.id,
                WorkoutRoutine.deleted_at.is_(None),
                WorkoutRoutine.status == RoutineStatus.ACTIVE,
            )
            .order_by(WorkoutRoutine.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    today_routine: HomeRoutineSummary | None = None
    if active_routine is not None:
        next_day = (
            await db.execute(
                select(RoutineDay)
                .where(RoutineDay.routine_id == active_routine.id)
                .order_by(RoutineDay.day_number)
                .limit(1)
            )
        ).scalar_one_or_none()
        today_routine = HomeRoutineSummary(
            routine_id=str(active_routine.id),
            name=active_routine.name,
            next_day_label=next_day.label if next_day else None,
        )

    # 2) 최근 7일 볼륨
    since = datetime.utcnow() - timedelta(days=7)
    volume_q = await db.execute(
        select(func.coalesce(func.sum(WorkoutLogSet.weight_kg * WorkoutLogSet.reps), 0.0))
        .join(WorkoutLog, WorkoutLogSet.workout_log_id == WorkoutLog.id)
        .where(
            WorkoutLog.user_id == current_user.id,
            WorkoutLog.started_at >= since,
            WorkoutLogSet.is_completed.is_(True),
        )
    )
    recent_volume = float(volume_q.scalar() or 0.0)

    # 3) 미확인 알림 상위 5개
    notifs = (
        (
            await db.execute(
                select(Notification)
                .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
                .order_by(Notification.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    notif_items = [
        NotificationItem(
            notification_id=str(n.id),
            type=n.type.value if n.type else "system",
            title=n.title,
            body=n.body,
            is_read=n.is_read,
            data=n.data_json,
            created_at=n.created_at,
        )
        for n in notifs
    ]

    # 4) 연속 일수 — sessions.py의 _compute_streak를 import 해서 재사용해도 되지만 의존성 단순화를 위해 인라인
    rows = (
        await db.execute(
            select(func.date(WorkoutLog.started_at)).where(WorkoutLog.user_id == current_user.id).distinct()
        )
    ).all()
    dates = sorted({r[0] for r in rows}, reverse=True)
    streak = 0
    if dates:
        today = datetime.now(timezone.utc).date()
        if dates[0] == today or dates[0] == today - timedelta(days=1):
            streak = 1
            cursor = dates[0]
            for d in dates[1:]:
                if d == cursor - timedelta(days=1):
                    streak += 1
                    cursor = d
                else:
                    break

    return SuccessResponse(
        data=HomeData(
            user_name=current_user.name,
            streak_days=streak,
            today_routine=today_routine,
            upcoming_notifications=notif_items,
            recent_volume_kg=round(recent_volume, 2),
        )
    )
