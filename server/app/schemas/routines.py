"""루틴 도메인 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

# ── AI 루틴 상세 조회 전용 ─────────────────────────────────────────────────────


class SetItem(BaseModel):
    set_number: int
    weight_kg: float | None = None
    reps: int | None = None
    rest_seconds: int
    completed: bool = False
    completed_at: datetime | None = None


class MuscleActivationDetailItem(BaseModel):
    muscle: str
    muscle_en: str
    percentage: int | None = None
    type: str


class ExerciseDetailItem(BaseModel):
    order: int
    exercise_id: str
    name: str
    name_en: str | None = None
    gif_url: str | None = None
    thumbnail_url: str | None = None
    category: str | None = None
    equipment: str | None = None
    difficulty: str | None = None
    mechanic: str | None = None
    force: str | None = None
    muscle_activation: list[MuscleActivationDetailItem] = Field(default_factory=list)
    sets: list[SetItem] = Field(default_factory=list)
    tips_count: int = 0
    tips_available: bool = False
    calories_per_minute: float | None = None
    met: float | None = None
    is_replaceable: bool = True


class AIRoutineDetail(BaseModel):
    routine_id: str
    title: str
    goal: str | None = None
    estimated_duration_min: int | None = None
    default_rest_seconds: int | None = None
    created_by: str
    created_at: datetime
    exercises: list[ExerciseDetailItem] = Field(default_factory=list)


# ── 공통 ──────────────────────────────────────────────────────────────────────
class MuscleActivationItem(BaseModel):
    muscle: str
    activation_pct: int | None = None


class RoutineExerciseItem(BaseModel):
    routine_exercise_id: str
    exercise_id: str
    exercise_name: str
    equipment_id: str | None = None
    equipment_name: str | None = None
    brand: str | None = None
    order_index: int
    sets: int
    reps_min: int | None = None
    reps_max: int | None = None
    weight_kg: float | None = None
    rest_seconds: int
    note: str | None = None
    has_paper: bool = False
    has_tips: bool = False
    muscle_activation: list[MuscleActivationItem] = Field(default_factory=list)


class RoutineDayItem(BaseModel):
    routine_day_id: str
    day_number: int
    label: str
    total_minutes: int | None = None
    exercises: list[RoutineExerciseItem] = Field(default_factory=list)


class GymSummary(BaseModel):
    gym_id: str
    name: str


class RoutineSummary(BaseModel):
    routine_id: str
    name: str
    fitness_goals: list[str] | None = None
    split_type: str | None = None
    generated_by: str
    status: str
    gym_id: str | None = None
    gym_name: str | None = None
    created_at: datetime
    updated_at: datetime


class RoutineDetail(RoutineSummary):
    target_muscle_group_ids: list | None = None
    session_minutes: int | None = None
    ai_reasoning: str | None = None
    gym: GymSummary | None = None
    days: list[RoutineDayItem] = Field(default_factory=list)


class RoutineListData(BaseModel):
    items: list[RoutineSummary]


# ── 생성/재생성 ───────────────────────────────────────────────────────────────
class GenerateRoutineRequest(BaseModel):
    goals: list[str]
    target_muscle_group_ids: list[str] = Field(default_factory=list)
    session_minutes: int | None = None
    split_type: str | None = None
    gym_id: str | None = None
    injury: str | None = Field(default=None, description="부상 정보 (예: 허리 통증으로 하체 운동 제외)")


class RegenerateRoutineRequest(BaseModel):
    feedback: str | None = Field(default=None, description="이전 루틴 대비 변경 요청")


# ── 부분 수정 ─────────────────────────────────────────────────────────────────
class UpdateRoutineNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateRoutineExerciseRequest(BaseModel):
    """PATCH /routines/{id}/exercises/{exId} — 보낸 필드만 부분 업데이트 (PATCH semantics)."""

    exercise_id: str | None = None
    equipment_id: str | None = None
    sets: int | None = Field(default=None, ge=1)
    reps_min: int | None = Field(default=None, ge=1)
    reps_max: int | None = Field(default=None, ge=1)
    weight_kg: float | None = Field(default=None, ge=0)
    rest_seconds: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=500)


# ── 논문 ──────────────────────────────────────────────────────────────────────
class PaperItem(BaseModel):
    paper_id: str
    title: str
    authors: str | None = None
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    relevance_summary: str | None = None

    @computed_field
    @property
    def doi_url(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None


class RoutineExercisePapersData(BaseModel):
    routine_exercise_id: str
    items: list[PaperItem]


# ── 삭제 ──────────────────────────────────────────────────────────────────────
class RoutineDeleteData(BaseModel):
    routine_id: str
    deleted_at: datetime
