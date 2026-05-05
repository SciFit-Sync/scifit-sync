import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class WorkoutStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    routine_day_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routine_days.id", ondelete="SET NULL"), default=None
    )
    gym_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="SET NULL"), default=None
    )
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[WorkoutStatus] = mapped_column(
        Enum(WorkoutStatus, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=WorkoutStatus.IN_PROGRESS,
        server_default=text("'in_progress'"),
    )

    sets: Mapped[list["WorkoutLogSet"]] = relationship(back_populates="workout_log", cascade="all, delete-orphan")


class WorkoutLogSet(Base):
    __tablename__ = "workout_log_sets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    workout_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_logs.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"))
    routine_exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routine_exercises.id", ondelete="SET NULL"), default=None
    )
    set_number: Mapped[int] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(default=None)
    reps: Mapped[int] = mapped_column(Integer)
    rpe: Mapped[float | None] = mapped_column(default=None)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    performed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    workout_log: Mapped["WorkoutLog"] = relationship(back_populates="sets")
