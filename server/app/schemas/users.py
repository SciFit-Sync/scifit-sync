"""사용자 도메인 Pydantic 스키마."""

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


# ── 응답: GET /users/me ────────────────────────────────────────────────────────
class CoreLift1RMItem(BaseModel):
    code: str
    name: str
    weight_kg: float | None = None


class ProfileData(BaseModel):
    gender: str | None = None
    birth_date: date | None = None
    age: int | None = None
    height_cm: float | None = None
    default_goals: list[str] | None = None
    career_level: str | None = None
    career_years: int | None = None


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
    core_lifts_1rm: list[CoreLift1RMItem] = Field(default_factory=list)


# ── POST /users/me/onboard ───────────────────────────────────────────────────
class OnboardRequest(BaseModel):
    gender: str = Field(..., pattern="^(male|female)$")
    birth_date: date
    height_cm: float = Field(..., gt=0)
    weight_kg: float = Field(..., gt=0)
    career_level: str
    career_years: int | None = Field(default=None, ge=0)
    default_goals: list[str] = Field(default_factory=list)


class OnboardData(BaseModel):
    user_id: str
    profile: ProfileData


# ── PATCH /users/me/body ──────────────────────────────────────────────────────
class UpdateBodyRequest(BaseModel):
    height_cm: float | None = Field(default=None, ge=50, le=300)
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    skeletal_muscle_kg: float | None = Field(default=None, ge=0, le=200)
    body_fat_pct: float | None = Field(default=None, ge=0, le=100)
    measured_at: date | None = None
    birth_date: date | None = None
    gender: str | None = None

    @field_validator("measured_at")
    @classmethod
    def validate_measured_at(cls, v: date | None) -> date | None:
        if v is None:
            return v
        today = date.today()
        if v > today:
            raise ValueError("측정일은 오늘보다 이전이어야 합니다.")
        if today.year - v.year > 10:
            raise ValueError("측정일이 너무 오래되었습니다.")
        return v

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, v: date | None) -> date | None:
        if v is None:
            return v
        today = date.today()
        if v > today:
            raise ValueError("생년월일은 오늘보다 이전이어야 합니다.")
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < 10 or age > 100:
            raise ValueError("만 나이가 10~100세 범위여야 합니다.")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v.lower() not in ("male", "female"):
            raise ValueError("gender는 'male' 또는 'female'이어야 합니다.")
        return v.lower()


class UpdateBodyData(BaseModel):
    height_cm: float | None = None
    birth_date: date | None = None
    gender: str | None = None
    measurement: BodyMeasurementData | None = None


# ── PATCH /users/me/goal ──────────────────────────────────────────────────────
_VALID_GOALS = {"hypertrophy", "strength", "endurance", "rehabilitation", "weight_loss"}


class UpdateGoalRequest(BaseModel):
    goals: list[str]

    @field_validator("goals")
    @classmethod
    def validate_goals(cls, v: list[str]) -> list[str]:
        result = []
        for goal in v:
            g = goal.lower()
            if g not in _VALID_GOALS:
                raise ValueError(f"goals 허용값: {sorted(_VALID_GOALS)}")
            result.append(g)
        return result


# ── PATCH /users/me/career ────────────────────────────────────────────────────
class UpdateCareerRequest(BaseModel):
    career_level: str
    career_years: int | None = Field(default=None, ge=0)


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
    bar_weight: float | None = None
    image_url: str | None = None


class UserEquipmentListData(BaseModel):
    items: list[UserEquipmentItem]


class AddUserEquipmentRequest(BaseModel):
    equipment_id: str
