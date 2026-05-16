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
    equipment_count: int = 0


class GymSearchData(BaseModel):
    gyms: list[GymItem]


class CreateGymRequest(BaseModel):
    name: str
    address: str
    latitude: float
    longitude: float
    kakao_place_id: str | None = None


# ── 장비 ──────────────────────────────────────────────────────────────────────
class EquipmentItem(BaseModel):
    equipment_id: str
    name: str
    brand: str | None = None
    category: str | None = None
    equipment_type: str | None = None
    pulley_ratio: float | None = None
    stack_weight_kg: float | None = None
    bar_weight_kg: float | None = None
    image_url: str | None = None


class BrandItem(BaseModel):
    brand_id: str
    name: str
    logo_url: str | None = None


class BrandListData(BaseModel):
    items: list[BrandItem]


class EquipmentListData(BaseModel):
    items: list[EquipmentItem]


class GymEquipmentListData(BaseModel):
    gym_id: str
    gym_name: str
    equipment: list[EquipmentItem]


class AddGymEquipmentRequest(BaseModel):
    equipment_id: str
    quantity: int = Field(default=1, ge=1)


class BulkAddEquipmentRequest(BaseModel):
    equipment_ids: list[str]


class BulkLinkData(BaseModel):
    gym_id: str
    linked_count: int
    message: str


class ReportEquipmentRequest(BaseModel):
    equipment_id: str
    report_type: str = Field(description="missing / broken / wrong_specs")
    description: str | None = None


class ReportData(BaseModel):
    report_id: str
    status: str


class SuggestEquipmentRequest(BaseModel):
    name: str
    brand: str | None = None
    description: str | None = None


class SuggestEquipmentData(BaseModel):
    message: str


class SelectEquipmentRequest(BaseModel):
    equipment_ids: list[str]


class SelectData(BaseModel):
    selected_count: int


# ── 운동 ──────────────────────────────────────────────────────────────────────
class ExerciseItem(BaseModel):
    exercise_id: str
    name: str
    name_en: str | None = None
    primary_muscle_groups: list[str] = Field(default_factory=list)
    secondary_muscle_groups: list[str] = Field(default_factory=list)
    equipment_id: str | None = None


class ExerciseListData(BaseModel):
    items: list[ExerciseItem]
    total_count: int
    page: int
    total_pages: int
