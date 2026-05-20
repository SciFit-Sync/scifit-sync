"""알림 도메인 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    notification_id: str
    type: str
    title: str
    body: str
    is_read: bool
    data: dict | None = None
    created_at: datetime


class NotificationListData(BaseModel):
    items: list[NotificationItem]
    unread_count: int = 0


# ── /home ─────────────────────────────────────────────────────────────────────
class HomeRoutineSummary(BaseModel):
    routine_id: str
    name: str
    next_day_label: str | None = None


class HomeData(BaseModel):
    user_name: str
    streak_days: int
    today_routine: HomeRoutineSummary | None = None
    upcoming_notifications: list[NotificationItem] = Field(default_factory=list)
    recent_volume_kg: float = 0.0
