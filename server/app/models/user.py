import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class FitnessGoal(str, enum.Enum):
    HYPERTROPHY = "hypertrophy"
    STRENGTH = "strength"
    ENDURANCE = "endurance"
    REHABILITATION = "rehabilitation"


class CareerLevel(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    failed_login_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(default=None)

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    body_measurements: Mapped[list["UserBodyMeasurement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    exercise_1rms: Mapped[list["UserExercise1RM"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    equipment_selections: Mapped[list["UserEquipmentSelection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(TimestampMixin, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    gender: Mapped[str | None] = mapped_column(String(10), default=None)
    age: Mapped[int | None] = mapped_column(default=None)
    fitness_goal: Mapped[FitnessGoal | None] = mapped_column(default=None)
    career_level: Mapped[CareerLevel | None] = mapped_column(default=None)
    workout_days_per_week: Mapped[int | None] = mapped_column(default=None)

    user: Mapped["User"] = relationship(back_populates="profile")


class UserBodyMeasurement(TimestampMixin, Base):
    __tablename__ = "user_body_measurements"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    height_cm: Mapped[float | None] = mapped_column(default=None)
    weight_kg: Mapped[float | None] = mapped_column(default=None)
    body_fat_pct: Mapped[float | None] = mapped_column(default=None)
    skeletal_muscle_kg: Mapped[float | None] = mapped_column(default=None)
    measured_at: Mapped[datetime] = mapped_column(server_default="now()")

    user: Mapped["User"] = relationship(back_populates="body_measurements")


class UserExercise1RM(TimestampMixin, Base):
    __tablename__ = "user_exercise_1rm"
    __table_args__ = (UniqueConstraint("user_id", "exercise_id", name="uq_user_exercise_1rm"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"))
    weight_kg: Mapped[float]
    estimated_at: Mapped[datetime] = mapped_column(server_default="now()")

    user: Mapped["User"] = relationship(back_populates="exercise_1rms")
    exercise: Mapped["Exercise"] = relationship()  # noqa: F821


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id"), default=None
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class UserEquipmentSelection(TimestampMixin, Base):
    __tablename__ = "user_equipment_selections"
    __table_args__ = (UniqueConstraint("user_id", "gym_equipment_id", name="uq_user_gym_equipment_selection"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gym_equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gym_equipments.id", ondelete="CASCADE")
    )

    user: Mapped["User"] = relationship(back_populates="equipment_selections")
    gym_equipment: Mapped["GymEquipment"] = relationship()  # noqa: F821


# Forward references resolved at import time via models/__init__.py
from app.models.exercise import Exercise  # noqa: E402, F401
from app.models.gym import GymEquipment  # noqa: E402, F401
