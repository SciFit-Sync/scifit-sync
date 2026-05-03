import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationType(enum.StrEnum):
    WORKOUT_REMINDER = "workout_reminder"
    MOTIVATION = "motivation"
    PO_SUGGESTION = "po_suggestion"
    SKIP_WARNING = "skip_warning"
    SYSTEM = "system"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x])
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    data_json: Mapped[dict | None] = mapped_column(JSON, default=None)
