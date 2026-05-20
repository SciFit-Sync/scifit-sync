"""알림 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #40-41.
"""

import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models import Notification, User
from app.schemas.common import SuccessResponse
from app.schemas.notifications import NotificationItem, NotificationListData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _parse_uuid(v: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise ValidationError(message=f"잘못된 {name} 형식입니다.") from e


def _to_dto(n: Notification) -> NotificationItem:
    return NotificationItem(
        notification_id=str(n.id),
        type=n.type.value if n.type else "system",
        title=n.title,
        body=n.body,
        is_read=n.is_read,
        data=n.data_json,
        created_at=n.created_at,
    )


@router.get("", response_model=SuccessResponse[NotificationListData], summary="알림 목록")
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(Notification)
                .where(Notification.user_id == current_user.id)
                .order_by(Notification.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    unread = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == current_user.id, Notification.is_read.is_(False)
            )
        )
    ).scalar() or 0

    return SuccessResponse(data=NotificationListData(items=[_to_dto(n) for n in rows], unread_count=int(unread)))


@router.patch(
    "/{notification_id}/read",
    response_model=SuccessResponse[NotificationItem],
    summary="알림 읽음 처리",
)
async def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    nid = _parse_uuid(notification_id, "notification_id")
    n = (
        await db.execute(select(Notification).where(Notification.id == nid, Notification.user_id == current_user.id))
    ).scalar_one_or_none()
    if n is None:
        raise NotFoundError(message="알림을 찾을 수 없습니다.")
    n.is_read = True
    await db.commit()
    await db.refresh(n)
    return SuccessResponse(data=_to_dto(n))
