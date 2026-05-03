import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, Enum, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Gender(enum.StrEnum):
    MALE = "male"
    FEMALE = "female"


class Provider(enum.StrEnum):
    LOCAL = "local"
    KAKAO = "kakao"


class CareerLevel(enum.StrEnum):
    BEGINNER = "beginner"
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class OnermSource(enum.StrEnum):
    MANUAL = "manual"
    EPLEY = "epley"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20), default=None)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    provider: Mapped[Provider] = mapped_column(
        Enum(Provider, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=Provider.LOCAL, server_default=text("'local'")
    )
    provider_id: Mapped[str | None] = mapped_column(String(100), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    body_measurements: Mapped[list["UserBodyMeasurement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    exercise_1rms: Mapped[list["UserExercise1RM"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x])
    )
    birth_date: Mapped[date] = mapped_column(Date)
    height_cm: Mapped[float]
    default_goals: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)
    career_level: Mapped[CareerLevel] = mapped_column(
        Enum(CareerLevel, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x])
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="profile")


class UserBodyMeasurement(Base):
    __tablename__ = "user_body_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    weight_kg: Mapped[float]
    skeletal_muscle_kg: Mapped[float | None] = mapped_column(default=None)
    body_fat_pct: Mapped[float | None] = mapped_column(default=None)
    measured_at: Mapped[date] = mapped_column(Date)

    user: Mapped["User"] = relationship(back_populates="body_measurements")


class UserExercise1RM(Base):
    __tablename__ = "user_exercise_1rm"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE")
    )
    weight_kg: Mapped[float]
    source: Mapped[OnermSource] = mapped_column(
        Enum(OnermSource, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x]),
        default=OnermSource.MANUAL, server_default=text("'manual'")
    )
    estimated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    user: Mapped["User"] = relationship(back_populates="exercise_1rms")
    exercise: Mapped["Exercise"] = relationship()  # noqa: F821


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
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
    device_info: Mapped[str | None] = mapped_column(String(255), default=None)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


from app.models.exercise import Exercise  # noqa: E402, F401
