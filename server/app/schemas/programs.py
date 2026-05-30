"""프로그램 도메인 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class ProgramRoutineItem(BaseModel):
    routine_id: str
    name: str
    gym_name: str | None = None
    order_index: int


class ProgramItem(BaseModel):
    program_id: str
    name: str
    description: str | None = None
    created_at: datetime
    routines: list[ProgramRoutineItem] = Field(default_factory=list)


class ProgramListData(BaseModel):
    items: list[ProgramItem]


class CreateProgramRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    routine_ids: list[str] = Field(..., min_length=1)


class UpdateProgramRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class DeleteProgramData(BaseModel):
    message: str
