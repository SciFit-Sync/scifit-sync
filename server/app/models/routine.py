import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class GeneratedBy(enum.StrEnum):
    USER = "user"
    AI = "ai"


class RoutineStatus(enum.StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SplitType(enum.StrEnum):
    TWO = "2split"
    THREE = "3split"
    FOUR = "4split"
    FIVE = "5split"


class WorkoutRoutine(TimestampMixin, Base):
    __tablename__ = "workout_routines"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gym_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="SET NULL"), default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    fitness_goals: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)
    target_muscle_group_ids: Mapped[list | None] = mapped_column(JSONB, default=None)
    session_duration_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    split_type: Mapped[SplitType | None] = mapped_column(
        Enum(SplitType, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=None,
    )
    generated_by: Mapped[GeneratedBy] = mapped_column(
        Enum(GeneratedBy, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=GeneratedBy.USER,
        server_default=text("'user'"),
    )
    status: Mapped[RoutineStatus] = mapped_column(
        Enum(RoutineStatus, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=RoutineStatus.ACTIVE,
        server_default=text("'active'"),
    )
    ai_reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    days: Mapped[list["RoutineDay"]] = relationship(back_populates="routine", cascade="all, delete-orphan")
    papers: Mapped[list["RoutinePaper"]] = relationship(back_populates="routine", cascade="all, delete-orphan")


class RoutineDay(Base):
    __tablename__ = "routine_days"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    routine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_routines.id", ondelete="CASCADE"), index=True
    )
    day_number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(200))

    routine: Mapped["WorkoutRoutine"] = relationship(back_populates="days")
    exercises: Mapped[list["RoutineExercise"]] = relationship(
        back_populates="routine_day", cascade="all, delete-orphan"
    )


class RoutineExercise(Base):
    __tablename__ = "routine_exercises"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    routine_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routine_days.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"))
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="SET NULL"), default=None
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sets: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    reps_min: Mapped[int | None] = mapped_column(Integer, default=None)
    reps_max: Mapped[int | None] = mapped_column(Integer, default=None)
    weight_kg: Mapped[float | None] = mapped_column(default=None)
    rest_seconds: Mapped[int] = mapped_column(Integer, default=60, server_default=text("60"))
    note: Mapped[str | None] = mapped_column(Text, default=None)

    routine_day: Mapped["RoutineDay"] = relationship(back_populates="exercises")
    exercise: Mapped["Exercise"] = relationship()  # noqa: F821
    equipment: Mapped["Equipment | None"] = relationship()  # noqa: F821


class RoutinePaper(Base):
    __tablename__ = "routine_papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    routine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_routines.id", ondelete="CASCADE"), index=True
    )
    routine_exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routine_exercises.id", ondelete="SET NULL"), default=None
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"))
    relevance_summary: Mapped[str | None] = mapped_column(Text, default=None)

    routine: Mapped["WorkoutRoutine"] = relationship(back_populates="papers")
    paper: Mapped["Paper"] = relationship()  # noqa: F821


class Program(TimestampMixin, Base):
    __tablename__ = "programs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    program_routines: Mapped[list["ProgramRoutine"]] = relationship(
        back_populates="program", cascade="all, delete-orphan"
    )


class ProgramRoutine(Base):
    __tablename__ = "program_routines"

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), primary_key=True
    )
    routine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_routines.id", ondelete="CASCADE"), primary_key=True
    )
    order_index: Mapped[int] = mapped_column(Integer)

    program: Mapped["Program"] = relationship(back_populates="program_routines")
    routine: Mapped["WorkoutRoutine"] = relationship()


from app.models.chat import Paper  # noqa: E402, F401
from app.models.exercise import Exercise  # noqa: E402, F401
from app.models.gym import Equipment, Gym  # noqa: E402, F401
