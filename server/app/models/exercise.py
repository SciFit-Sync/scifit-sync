import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MuscleInvolvement(enum.StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    STABILIZER = "stabilizer"


class Exercise(TimestampMixin, Base):
    __tablename__ = "exercises"

    name: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    category: Mapped[str] = mapped_column(String(50))
    gif_url: Mapped[str | None] = mapped_column(String(500), default=None)
    # WorkoutX 재설계: 부하 계산 분기 기준 load_mode (barbell/ez_barbell/trap_bar/dumbbell/
    # bodyweight/weighted/kettlebell/band/cable/machine/cardio). nullable — 재시드가 채움.
    load_mode: Mapped[str | None] = mapped_column(String(20), default=None)

    # 기구↔운동 N:M (머신 운동만 행 보유. 프리웨이트=행 없음 → routine_exercises.equipment_id NULL).
    equipment_links: Mapped[list["ExerciseEquipment"]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan"
    )
    muscle_maps: Mapped[list["ExerciseMuscle"]] = relationship(back_populates="exercise", cascade="all, delete-orphan")


class ExerciseEquipment(Base):
    """기구↔운동 N:M 정션 (eem 폐기 후 신설). 머신 운동만 행 보유, 프리웨이트는 행 없음."""

    __tablename__ = "exercise_equipment"

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(20), default="seed", server_default=text("'seed'"))
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), default=None)

    exercise: Mapped["Exercise"] = relationship(back_populates="equipment_links")
    equipment: Mapped["Equipment"] = relationship()  # noqa: F821


class MuscleGroup(Base):
    __tablename__ = "muscle_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default="gen_random_uuid()",
    )
    name: Mapped[str] = mapped_column(String(100), unique=True)
    name_ko: Mapped[str] = mapped_column(String(100), unique=True)
    body_region: Mapped[str] = mapped_column(String(50))


class ExerciseMuscle(Base):
    __tablename__ = "exercise_muscles"

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    muscle_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("muscle_groups.id", ondelete="RESTRICT"), primary_key=True
    )
    involvement: Mapped[MuscleInvolvement] = mapped_column(
        Enum(
            MuscleInvolvement,
            native_enum=False,
            create_constraint=False,
            values_callable=lambda x: [e.value for e in x],
        )
    )
    activation_pct: Mapped[int | None] = mapped_column(Integer, default=None)

    exercise: Mapped["Exercise"] = relationship(back_populates="muscle_maps")
    muscle_group: Mapped["MuscleGroup"] = relationship()


from app.models.gym import Equipment  # noqa: E402, F401
