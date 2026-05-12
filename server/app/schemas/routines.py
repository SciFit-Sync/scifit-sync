"""루틴 도메인 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 공통 ──────────────────────────────────────────────────────────────────────
class RoutineExerciseItem(BaseModel):
    routine_exercise_id: str
    exercise_id: str
    exercise_name: str
    equipment_id: str | None = None
    equipment_name: str | None = None
    order_index: int
    sets: int
    reps_min: int | None = None
    reps_max: int | None = None
    weight_kg: float | None = None
    rest_seconds: int
    note: str | None = None
    has_paper: bool = False


class RoutineDayItem(BaseModel):
    routine_day_id: str
    day_number: int
    label: str
    exercises: list[RoutineExerciseItem] = Field(default_factory=list)


class RoutineSummary(BaseModel):
    routine_id: str
    name: str
    fitness_goals: list[str] | None = None
    split_type: str | None = None
    generated_by: str
    status: str
    created_at: datetime
    updated_at: datetime


class RoutineDetail(RoutineSummary):
    target_muscle_group_ids: list | None = None
    session_duration_minutes: int | None = None
    ai_reasoning: str | None = None
    days: list[RoutineDayItem] = Field(default_factory=list)


class RoutineListData(BaseModel):
    items: list[RoutineSummary]


# ── 생성/재생성 ───────────────────────────────────────────────────────────────
class GenerateRoutineRequest(BaseModel):
    goals: list[str]
    split_type: str | None = None
    session_duration_minutes: int | None = None
    target_muscle_group_ids: list[str] = Field(default_factory=list)
    gym_id: str | None = None


class RegenerateRoutineRequest(BaseModel):
    feedback: str | None = Field(default=None, description="이전 루틴 대비 변경 요청")


# ── 부분 수정 ─────────────────────────────────────────────────────────────────
class UpdateRoutineNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateRoutineExerciseRequest(BaseModel):
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
