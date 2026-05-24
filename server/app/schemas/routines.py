"""루틴 도메인 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


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
    new_exercise_id: str | None = None
    sets: int | None = Field(default=None, ge=1)
    reps_min: int | None = Field(default=None, ge=1)
    reps_max: int | None = Field(default=None, ge=1)
    weight_kg: float | None = None
    rest_seconds: int | None = Field(default=None, ge=0)
    note: str | None = None


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


class RoutineExercisePapersData(BaseModel):
    routine_exercise_id: str
    items: list[PaperItem]


# ── 종목 교체 ─────────────────────────────────────────────────────────────────
class ReplaceRoutineExerciseRequest(BaseModel):
    new_exercise_id: str


class ReplacedExerciseData(BaseModel):
    exercise_id: str
    name: str
    equipment: str | None = None
    brand: str | None = None
    sets: int
    reps_min: int | None = None
    reps_max: int | None = None


class ReplaceRoutineExerciseData(BaseModel):
    message: str
    new_exercise: ReplacedExerciseData


# ── 삭제 ──────────────────────────────────────────────────────────────────────
class RoutineDeleteData(BaseModel):
    routine_id: str
    deleted_at: datetime
