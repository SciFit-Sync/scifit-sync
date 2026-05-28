"""세션(운동 로그) Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 세션 생성 ─────────────────────────────────────────────────────────────────
class StartSessionRequest(BaseModel):
    routine_id: str | None = None
    routine_day_id: str | None = None
    gym_id: str | None = None


class SessionStartData(BaseModel):
    session_id: str
    routine_id: str | None = None
    routine_name: str | None = None
    gym_id: str | None = None
    started_at: datetime
    message: str = "운동을 시작합니다!"


class SessionData(BaseModel):
    session_id: str
    routine_day_id: str | None = None
    gym_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    routine_name: str | None = None
    duration_minutes: int | None = None
    total_sets: int | None = None
    completed_exercises: int | None = None
    total_calories: int | None = None


# ── 세트 기록 ─────────────────────────────────────────────────────────────────
class LogSetRequest(BaseModel):
    exercise_id: str
    routine_exercise_id: str | None = None
    set_number: int = Field(ge=1)
    weight_kg: float | None = None
    reps: int = Field(ge=0)
    rpe: float | None = Field(default=None, ge=1.0, le=10.0)
    is_completed: bool = True


class WorkoutSetItem(BaseModel):
    set_id: str
    exercise_id: str
    exercise_name: str | None = None
    set_number: int
    weight_kg: float | None = None
    reps: int
    rpe: float | None = None
    is_completed: bool
    performed_at: datetime


# ── 세션 종료 ─────────────────────────────────────────────────────────────────
class FinishSessionRequest(BaseModel):
    finished_at: datetime | None = None


# ── 세션 상세 ─────────────────────────────────────────────────────────────────
class SessionDetail(SessionData):
    sets: list[WorkoutSetItem] = Field(default_factory=list)
    total_volume_kg: float = 0.0


class SessionCalendarItem(BaseModel):
    date: str  # YYYY-MM-DD
    session_id: str
    routine_name: str | None = None
    duration_minutes: int | None = None


class SessionCalendarData(BaseModel):
    year: int
    month: int
    records: list[SessionCalendarItem]
    total_session_count: int


class SessionListData(BaseModel):
    items: list[SessionData]


# ── 통계 ──────────────────────────────────────────────────────────────────────
class RecentSessionItem(BaseModel):
    session_id: str
    routine_name: str | None = None
    date: str  # YYYY-MM-DD


class GymStatItem(BaseModel):
    gym_id: str
    gym_name: str
    session_count: int
    total_volume_kg: float


class SessionStatsData(BaseModel):
    total_sessions: int
    total_volume_kg: float
    total_duration_minutes: int
    total_sets: int = 0
    weekly_session_count: int = 0
    streak_days: int
    recent_session: RecentSessionItem | None = None
    by_gym: list[GymStatItem] = Field(default_factory=list)


class VolumeAnalysisItem(BaseModel):
    date: str  # YYYY-MM-DD
    volume_kg: float


class VolumeAnalysisData(BaseModel):
    items: list[VolumeAnalysisItem]


# ── 근육 볼륨 분석 ───────────────────────────────────────────────────────────
class MuscleVolumeItem(BaseModel):
    muscle: str  # MuscleGroup.name_ko
    weekly_volume: float
    optimal_min: float
    optimal_max: float
    status: str  # "OPTIMAL" | "LOW" | "HIGH"


class MuscleVolumeData(BaseModel):
    period: str  # "WEEK" | "MONTH"
    volume_by_muscle: list[MuscleVolumeItem]
    ai_coach_message: str


# ── 휴식 타이머 ──────────────────────────────────────────────────────────────
class RestTimerData(BaseModel):
    rest_seconds: int
    min_rest_seconds: int
    max_rest_seconds: int
    message: str
    based_on: str  # "routine" | "goal_default"
