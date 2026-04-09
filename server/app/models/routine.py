import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WorkoutRoutine(TimestampMixin, Base):
    __tablename__ = "workout_routines"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    fitness_goal: Mapped[str | None] = mapped_column(String(50), default=None)
    generated_by: Mapped[str | None] = mapped_column(String(100), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    days: Mapped[list["RoutineDay"]] = relationship(back_populates="routine", cascade="all, delete-orphan")
    papers: Mapped[list["RoutinePaper"]] = relationship(back_populates="routine", cascade="all, delete-orphan")


class RoutineDay(TimestampMixin, Base):
    __tablename__ = "routine_days"

    routine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_routines.id", ondelete="CASCADE"),
        index=True,
    )
    day_number: Mapped[int]
    name: Mapped[str | None] = mapped_column(String(200), default=None)

    routine: Mapped["WorkoutRoutine"] = relationship(back_populates="days")
    exercises: Mapped[list["RoutineExercise"]] = relationship(
        back_populates="routine_day", cascade="all, delete-orphan"
    )


class RoutineExercise(TimestampMixin, Base):
    __tablename__ = "routine_exercises"

    routine_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("routine_days.id", ondelete="CASCADE"),
        index=True,
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"))
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id"), default=None
    )
    order_index: Mapped[int] = mapped_column(default=0)
    sets: Mapped[int] = mapped_column(default=3)
    reps: Mapped[int] = mapped_column(default=10)
    weight_kg: Mapped[float | None] = mapped_column(default=None)
    rest_seconds: Mapped[int] = mapped_column(default=60)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    routine_day: Mapped["RoutineDay"] = relationship(back_populates="exercises")
    exercise: Mapped["Exercise"] = relationship()  # noqa: F821
    equipment: Mapped["Equipment | None"] = relationship()  # noqa: F821


class RoutinePaper(TimestampMixin, Base):
    __tablename__ = "routine_papers"

    routine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_routines.id", ondelete="CASCADE"),
        index=True,
    )
    routine_exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("routine_exercises.id", ondelete="CASCADE"),
        default=None,
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"))
    relevance_summary: Mapped[str | None] = mapped_column(Text, default=None)

    routine: Mapped["WorkoutRoutine"] = relationship(back_populates="papers")
    paper: Mapped["Paper"] = relationship()  # noqa: F821


from app.models.chat import Paper  # noqa: E402, F401
from app.models.exercise import Exercise  # noqa: E402, F401
from app.models.gym import Equipment  # noqa: E402, F401
