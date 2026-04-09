import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WorkoutLog(TimestampMixin, Base):
    __tablename__ = "workout_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    routine_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_routines.id"), default=None
    )
    started_at: Mapped[datetime] = mapped_column(server_default="now()")
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    sets: Mapped[list["WorkoutLogSet"]] = relationship(back_populates="workout_log", cascade="all, delete-orphan")


class WorkoutLogSet(TimestampMixin, Base):
    __tablename__ = "workout_log_sets"

    workout_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_logs.id", ondelete="CASCADE"),
        index=True,
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"))
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id"), default=None
    )
    set_number: Mapped[int]
    weight_kg: Mapped[float]
    reps: Mapped[int]
    is_completed: Mapped[bool] = mapped_column(default=True)
    rpe: Mapped[float | None] = mapped_column(default=None)

    workout_log: Mapped["WorkoutLog"] = relationship(back_populates="sets")
