"""헬스장/장비/운동 도메인 Pydantic 스키마."""

from pydantic import BaseModel, Field


# ── 헬스장 ────────────────────────────────────────────────────────────────────
class GymItem(BaseModel):
    gym_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    kakao_place_id: str | None = None


class GymSearchData(BaseModel):
    items: list[GymItem]


class CreateGymRequest(BaseModel):
    kakao_place_id: str
    name: str
    address: str
    latitude: float
    longitude: float


class CreateGymData(BaseModel):
    gym_id: str
    name: str
    message: str


# ── 장비 ──────────────────────────────────────────────────────────────────────
class EquipmentItem(BaseModel):
    equipment_id: str
    name: str
    name_en: str | None = None
    category: str | None = None
    equipment_type: str
    brand: str | None = None
    pulley_ratio: float | None = None
    bar_weight_kg: float | None = None
    has_weight_assist: bool = False
    min_stack_kg: float | None = None
    max_stack_kg: float | None = None
    stack_weight_kg: float | None = None
    image_url: str | None = None


class EquipmentListData(BaseModel):
    items: list[EquipmentItem]


class GymEquipmentListData(BaseModel):
    gym_id: str
    items: list[EquipmentItem]


class AddGymEquipmentRequest(BaseModel):
    equipment_id: str
    quantity: int = Field(default=1, ge=1)


class ReportEquipmentRequest(BaseModel):
    equipment_id: str
    report_type: str = Field(description="missing / broken / wrong_specs")
    description: str | None = None


class ReportData(BaseModel):
    report_id: str
    status: str


# ── 운동 ──────────────────────────────────────────────────────────────────────
class ExerciseItem(BaseModel):
    exercise_id: str
    name: str
    name_en: str | None = None
    description: str | None = None
    image_url: str | None = None
    primary_muscle_groups: list[str] = Field(default_factory=list)


class ExerciseListData(BaseModel):
    items: list[ExerciseItem]
