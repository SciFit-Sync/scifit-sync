"""사용자 도메인 Pydantic 스키마."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


# ── 응답: GET /users/me ────────────────────────────────────────────────────────
class UserBodyData(BaseModel):
    """신체 정보 (Notion 스펙 #9)."""

    gender: str | None = None
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None


class UserCareerData(BaseModel):
    """운동 경력 정보."""

    level: str | None = None
    description: str | None = None


class UserGymData(BaseModel):
    """주 헬스장 정보."""

    gym_id: str
    name: str


class MeData(BaseModel):
    user_id: str
    email: str
    name: str
    username: str
    body: UserBodyData | None = None
    career: UserCareerData | None = None
    gym: UserGymData | None = None
    one_rm: "OneRM4BigLiftData | None" = None


# ── 체측 내부 응답용 ───────────────────────────────────────────────────────────
class BodyMeasurementData(BaseModel):
    weight_kg: float | None = None
    skeletal_muscle_kg: float | None = None
    body_fat_pct: float | None = None
    measured_at: date | None = None


# 프로필 업데이트 응답 (goal 수정용)
class ProfileData(BaseModel):
    gender: str | None = None
    birth_date: date | None = None
    height_cm: float | None = None
    default_goals: list[str] | None = None
    career_level: str | None = None


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


class UpdateCareerData(BaseModel):
    message: str
    career_level: str


# ── /users/me/gym ─────────────────────────────────────────────────────────────
class SetPrimaryGymRequest(BaseModel):
    gym_id: str


# ── GymData (list_gyms 등 내부 사용) ──────────────────────────────────────────
class GymData(BaseModel):
    gym_id: str
    name: str
    is_primary: bool


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


class BulkOneRMItem(BaseModel):
    """exercise_id 또는 exercise_code 중 하나는 필수.
    code 예시: 'bench_press', 'squat', 'deadlift', 'overhead_press'"""

    exercise_id: str | None = None
    exercise_code: str | None = None
    weight_kg: float = Field(ge=0)
    reps: int | None = Field(default=None, ge=1)


class BulkAdd1RMRequest(BaseModel):
    items: list[BulkOneRMItem] = Field(min_length=1, max_length=20)


class BulkOneRMData(BaseModel):
    items: list[OneRMData]
    created_count: int


# ── 핵심 4대 운동 ────────────────────────────────────────────────────────────
class CoreLiftItem(BaseModel):
    code: str  # 'bench_press' / 'squat' / 'deadlift' / 'overhead_press'
    exercise_id: str
    name: str  # 한글 이름
    name_en: str | None = None


class CoreLiftsData(BaseModel):
    items: list[CoreLiftItem]


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
