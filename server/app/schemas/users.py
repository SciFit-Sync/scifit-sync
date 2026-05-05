"""사용자 도메인 Pydantic 스키마."""

from datetime import date, datetime

from pydantic import BaseModel, Field


# ── 응답: GET /users/me ────────────────────────────────────────────────────────
class ProfileData(BaseModel):
    gender: str | None = None
    birth_date: date | None = None
    height_cm: float | None = None
    default_goals: list[str] | None = None
    career_level: str | None = None


class BodyMeasurementData(BaseModel):
    weight_kg: float | None = None
    skeletal_muscle_kg: float | None = None
    body_fat_pct: float | None = None
    measured_at: date | None = None


class GymData(BaseModel):
    gym_id: str
    name: str
    is_primary: bool


class MeData(BaseModel):
    user_id: str
    email: str
    username: str
    name: str
    provider: str
    profile: ProfileData | None = None
    latest_measurement: BodyMeasurementData | None = None
    gyms: list[GymData] = Field(default_factory=list)


# ── PATCH /users/me/body ──────────────────────────────────────────────────────
class UpdateBodyRequest(BaseModel):
    height_cm: float | None = None
    weight_kg: float | None = None
    skeletal_muscle_kg: float | None = None
    body_fat_pct: float | None = None
    measured_at: date | None = None


class UpdateBodyData(BaseModel):
    height_cm: float | None = None
    measurement: BodyMeasurementData | None = None


# ── PATCH /users/me/goal ──────────────────────────────────────────────────────
class UpdateGoalRequest(BaseModel):
    goals: list[str]


# ── PATCH /users/me/career ────────────────────────────────────────────────────
class UpdateCareerRequest(BaseModel):
    career_level: str


# ── /users/me/gym ─────────────────────────────────────────────────────────────
class SetPrimaryGymRequest(BaseModel):
    gym_id: str


# ── 1RM ───────────────────────────────────────────────────────────────────────
class Add1RMRequest(BaseModel):
    exercise_id: str
    weight_kg: float
    reps: int | None = Field(default=None, description="제공 시 Epley 공식으로 1RM 추정")


class OneRMData(BaseModel):
    id: str
    exercise_id: str
    exercise_name: str | None = None
    weight_kg: float
    source: str
    estimated_at: datetime


class OneRMListData(BaseModel):
    items: list[OneRMData]


# ── /users/me/equipment ───────────────────────────────────────────────────────
class UserEquipmentItem(BaseModel):
    equipment_id: str
    name: str
    category: str | None = None
    equipment_type: str
    pulley_ratio: float | None = None
    bar_weight_kg: float | None = None
    image_url: str | None = None


class UserEquipmentListData(BaseModel):
    items: list[UserEquipmentItem]


class AddUserEquipmentRequest(BaseModel):
    equipment_id: str
