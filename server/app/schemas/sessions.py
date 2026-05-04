"""세션(운동 로그) Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


# ── 세션 생성 ─────────────────────────────────────────────────────────────────
class StartSessionRequest(BaseModel):
    routine_day_id: str | None = None
    gym_id: str | None = None


class SessionData(BaseModel):
    session_id: str
    routine_day_id: str | None = None
    gym_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: str


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


class SessionListData(BaseModel):
    items: list[SessionData]


# ── 통계 ──────────────────────────────────────────────────────────────────────
class SessionStatsData(BaseModel):
    total_sessions: int
    total_volume_kg: float
    total_minutes: int
    streak_days: int


class VolumeAnalysisItem(BaseModel):
    date: str  # YYYY-MM-DD
    volume_kg: float


class VolumeAnalysisData(BaseModel):
    items: list[VolumeAnalysisItem]


# ── 휴식 타이머 ──────────────────────────────────────────────────────────────
class RestTimerData(BaseModel):
    rest_seconds: int
    based_on: str  # "routine" | "goal_default"
