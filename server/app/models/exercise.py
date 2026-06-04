import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
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
    # PR-4.5: 프리웨이트 운동의 구현 기구(제네릭 바벨/덤벨) 단일 매핑. exercise_equipment_map 읽기 경로 대체.
    default_equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="SET NULL"), default=None
    )

    # DEPRECATED (PR-5에서 제거 예정): 런타임 읽기/쓰기 경로는 default_equipment_id로 이전됨.
    equipment_maps: Mapped[list["ExerciseEquipmentMap"]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan"
    )
    muscle_maps: Mapped[list["ExerciseMuscle"]] = relationship(back_populates="exercise", cascade="all, delete-orphan")


class ExerciseEquipmentMap(Base):
    __tablename__ = "exercise_equipment_map"

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="CASCADE"), primary_key=True
    )

    exercise: Mapped["Exercise"] = relationship(back_populates="equipment_maps")
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
