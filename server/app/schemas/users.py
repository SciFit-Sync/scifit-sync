"""사용자 도메인 Pydantic 스키마."""

from datetime import date
from typing import Literal

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


# ── 1RM (Big 4) ───────────────────────────────────────────────────────────────
class Set1RMRequest(BaseModel):
    unit: Literal["KG"] = Field(default="KG", description="중량 단위 (KG만 지원)")
    bench_press: float | None = Field(default=None, gt=0, description="벤치프레스 1RM (kg)")
    squat: float | None = Field(default=None, gt=0, description="스쿼트 1RM (kg)")
    deadlift: float | None = Field(default=None, gt=0, description="데드리프트 1RM (kg)")
    overhead_press: float | None = Field(default=None, gt=0, description="오버헤드프레스 1RM (kg)")


class OneRM4BigLiftData(BaseModel):
    unit: str
    bench_press: float | None = None
    squat: float | None = None
    deadlift: float | None = None
    overhead_press: float | None = None


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
