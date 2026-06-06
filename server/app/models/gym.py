import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Computed, Enum, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class WeightUnit(enum.StrEnum):
    KG = "kg"
    LB = "lb"


class EquipmentBodyCategory(enum.StrEnum):
    CHEST = "chest"
    BACK = "back"
    SHOULDERS = "shoulders"
    ARMS = "arms"
    CORE = "core"
    LEGS = "legs"


class EquipmentType(enum.StrEnum):
    CABLE = "cable"
    MACHINE = "machine"
    BARBELL = "barbell"
    DUMBBELL = "dumbbell"
    BODYWEIGHT = "bodyweight"


class EquipmentReportStatus(enum.StrEnum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"


class Gym(Base):
    __tablename__ = "gyms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    kakao_place_id: Mapped[str | None] = mapped_column(String(50), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500))
    latitude: Mapped[float]
    longitude: Mapped[float]

    gym_equipments: Mapped[list["GymEquipment"]] = relationship(back_populates="gym", cascade="all, delete-orphan")


class UserGym(Base):
    __tablename__ = "user_gyms"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    gym: Mapped["Gym"] = relationship()


class EquipmentBrand(Base):
    __tablename__ = "equipment_brands"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), unique=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), default=None)
    default_bar_unit: Mapped[WeightUnit] = mapped_column(
        Enum(WeightUnit, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=WeightUnit.KG,
        server_default="kg",
    )
    default_stack_unit: Mapped[WeightUnit] = mapped_column(
        Enum(WeightUnit, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=WeightUnit.KG,
        server_default="kg",
    )


class Equipment(Base):
    __tablename__ = "equipments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_brands.id", ondelete="SET NULL"), default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str | None] = mapped_column(String(200), default=None)
    sub_category: Mapped[str | None] = mapped_column(String(50), default=None)
    category: Mapped[EquipmentBodyCategory | None] = mapped_column(
        Enum(
            EquipmentBodyCategory,
            native_enum=False,
            create_constraint=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=None,
    )
    equipment_type: Mapped[EquipmentType] = mapped_column(
        Enum(EquipmentType, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x])
    )
    pulley_ratio: Mapped[float] = mapped_column(default=1.0, server_default=text("1.0"))
    bar_weight: Mapped[float | None] = mapped_column(default=None)
    bar_weight_unit: Mapped[WeightUnit | None] = mapped_column(
        Enum(WeightUnit, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=None,
    )
    has_weight_assist: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    min_stack: Mapped[float | None] = mapped_column(default=None)
    max_stack: Mapped[float | None] = mapped_column(default=None)
    stack_weight: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    stack_unit: Mapped[WeightUnit | None] = mapped_column(
        Enum(WeightUnit, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=None,
    )
    image_url: Mapped[str | None] = mapped_column(String(500), default=None)
    movement_label_ko: Mapped[str | None] = mapped_column(String(150), default=None)
    movement_label_en: Mapped[str | None] = mapped_column(String(150), default=None)
    is_freeweight: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed("equipment_type IN ('barbell', 'dumbbell', 'bodyweight')", persisted=True),
    )

    brand: Mapped["EquipmentBrand | None"] = relationship()


class GymEquipment(Base):
    __tablename__ = "gym_equipments"

    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(default=1, server_default=text("1"))

    gym: Mapped["Gym"] = relationship(back_populates="gym_equipments")
    equipment: Mapped["Equipment"] = relationship()


class EquipmentReport(Base):
    __tablename__ = "equipment_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gym_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"))
    equipment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="CASCADE"))
    report_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[EquipmentReportStatus] = mapped_column(
        Enum(
            EquipmentReportStatus,
            native_enum=False,
            create_constraint=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=EquipmentReportStatus.PENDING,
        server_default=text("'pending'"),
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)


class EquipmentMuscle(Base):
    __tablename__ = "equipment_muscles"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="CASCADE"), primary_key=True
    )
    muscle_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("muscle_groups.id", ondelete="RESTRICT"), primary_key=True
    )
    involvement: Mapped[str] = mapped_column(String(20))
    activation_pct: Mapped[int | None] = mapped_column(Integer, default=None)

    equipment: Mapped["Equipment"] = relationship()
    muscle_group: Mapped["MuscleGroup"] = relationship()  # noqa: F821


class EquipmentSuggestion(Base):
    __tablename__ = "equipment_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gym_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(100), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default=text("'pending'"))


from app.models.exercise import MuscleGroup  # noqa: E402, F401
