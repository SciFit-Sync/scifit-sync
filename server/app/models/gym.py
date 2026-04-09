import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class EquipmentCategory(str, enum.Enum):
    CABLE = "cable"
    MACHINE = "machine"
    BARBELL = "barbell"
    DUMBBELL = "dumbbell"
    BODYWEIGHT = "bodyweight"


class Gym(TimestampMixin, Base):
    __tablename__ = "gyms"

    kakao_place_id: Mapped[str | None] = mapped_column(String(50), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(500), default=None)
    latitude: Mapped[float | None] = mapped_column(default=None)
    longitude: Mapped[float | None] = mapped_column(default=None)

    gym_equipments: Mapped[list["GymEquipment"]] = relationship(back_populates="gym", cascade="all, delete-orphan")


class UserGym(TimestampMixin, Base):
    __tablename__ = "user_gyms"
    __table_args__ = (UniqueConstraint("user_id", "gym_id", name="uq_user_gym"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gym_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"))
    is_primary: Mapped[bool] = mapped_column(default=False)

    gym: Mapped["Gym"] = relationship()


class EquipmentBrand(TimestampMixin, Base):
    __tablename__ = "equipment_brands"

    name: Mapped[str] = mapped_column(String(100), unique=True)


class Equipment(TimestampMixin, Base):
    __tablename__ = "equipments"

    name: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str | None] = mapped_column(String(200), default=None)
    category: Mapped[EquipmentCategory]
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_brands.id"), default=None
    )
    pulley_ratio: Mapped[float] = mapped_column(default=1.0)
    bar_weight_kg: Mapped[float | None] = mapped_column(default=None)
    has_weight_assist: Mapped[bool] = mapped_column(default=False)
    max_stack_kg: Mapped[float | None] = mapped_column(default=None)
    weight_increment_kg: Mapped[float | None] = mapped_column(default=None)

    brand: Mapped["EquipmentBrand | None"] = relationship()


class GymEquipment(TimestampMixin, Base):
    __tablename__ = "gym_equipments"
    __table_args__ = (UniqueConstraint("gym_id", "equipment_id", name="uq_gym_equipment"),)

    gym_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), index=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("equipments.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(default=1)

    gym: Mapped["Gym"] = relationship(back_populates="gym_equipments")
    equipment: Mapped["Equipment"] = relationship()


class EquipmentReport(TimestampMixin, Base):
    __tablename__ = "equipment_reports"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gym_equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gym_equipments.id", ondelete="CASCADE")
    )
    report_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)
