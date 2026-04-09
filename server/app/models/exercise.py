import enum
import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MuscleInvolvement(str, enum.Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    STABILIZER = "stabilizer"


class Exercise(TimestampMixin, Base):
    __tablename__ = "exercises"

    name: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str | None] = mapped_column(String(200), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    category: Mapped[str | None] = mapped_column(String(50), default=None)

    equipment_maps: Mapped[list["ExerciseEquipmentMap"]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan"
    )
    muscle_maps: Mapped[list["ExerciseMuscle"]] = relationship(back_populates="exercise", cascade="all, delete-orphan")


class ExerciseEquipmentMap(TimestampMixin, Base):
    __tablename__ = "exercise_equipment_map"
    __table_args__ = (UniqueConstraint("exercise_id", "equipment_id", name="uq_exercise_equipment_map"),)

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="CASCADE"))

    exercise: Mapped["Exercise"] = relationship(back_populates="equipment_maps")
    equipment: Mapped["Equipment"] = relationship()  # noqa: F821


class MuscleGroup(TimestampMixin, Base):
    __tablename__ = "muscle_groups"

    name: Mapped[str] = mapped_column(String(100))
    name_en: Mapped[str | None] = mapped_column(String(100), default=None)
    body_region: Mapped[str | None] = mapped_column(String(50), default=None)


class ExerciseMuscle(TimestampMixin, Base):
    __tablename__ = "exercise_muscles"
    __table_args__ = (UniqueConstraint("exercise_id", "muscle_group_id", name="uq_exercise_muscle"),)

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    muscle_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("muscle_groups.id", ondelete="CASCADE")
    )
    involvement: Mapped[MuscleInvolvement]

    exercise: Mapped["Exercise"] = relationship(back_populates="muscle_maps")
    muscle_group: Mapped["MuscleGroup"] = relationship()


from app.models.gym import Equipment  # noqa: E402, F401
