import uuid

from pydantic import BaseModel

# ── Request ──────────────────────────────────────────────────────────────────


class GenerateRoutineRequest(BaseModel):
    goals: list[str]
    targetMuscles: list[str]
    sessionMinutes: int
    injury: str | None = None


class RenameRoutineRequest(BaseModel):
    name: str


class ReplaceExerciseRequest(BaseModel):
    newExerciseId: uuid.UUID


# ── Response data ─────────────────────────────────────────────────────────────


class RoutineSummary(BaseModel):
    routineId: str
    name: str
    goal: str | None
    targetMuscles: list[str]
    daysPerWeek: int
    sessionMinutes: int
    paperCount: int
    createdAt: str


class RoutineListData(BaseModel):
    routines: list[RoutineSummary]
    totalCount: int


class ExerciseDetail(BaseModel):
    exerciseId: str
    name: str
    equipment: str | None
    brand: str | None
    sets: int
    repsMin: int
    repsMax: int
    weightKg: float | None
    hasPaper: bool
    hasTips: bool = False


class RoutineDayDetail(BaseModel):
    dayNumber: int
    label: str | None
    totalMinutes: int
    exercises: list[ExerciseDetail]


class RoutineDetail(BaseModel):
    routineId: str
    name: str
    days: list[RoutineDayDetail]


class RenameRoutineData(BaseModel):
    routineId: str
    name: str


class NewExerciseData(BaseModel):
    exerciseId: str
    name: str
    equipment: str | None
    brand: str | None
    sets: int
    repsMin: int
    repsMax: int


class ReplaceExerciseData(BaseModel):
    message: str
    newExercise: NewExerciseData


class DeleteRoutineData(BaseModel):
    routineId: str
    deletedAt: str


class PaperData(BaseModel):
    paperId: str
    title: str
    authors: str | None
    journal: str | None
    publishedYear: int | None
    doi: str | None
    abstract: str | None
    relevanceSummary: str | None
