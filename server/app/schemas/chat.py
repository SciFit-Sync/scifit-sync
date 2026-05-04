"""챗봇 도메인 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatMessageItem(BaseModel):
    message_id: str
    role: str  # user / assistant
    content: str
    paper_ids: list[str] | None = None
    created_at: datetime


class ChatMessageListData(BaseModel):
    session_id: str
    items: list[ChatMessageItem]


class SendChatMessageRequest(BaseModel):
    session_id: str | None = Field(default=None, description="없으면 새 세션 생성")
    content: str = Field(min_length=1)


class RecommendedRoutineItem(BaseModel):
    title: str
    summary: str
    paper_ids: list[str] = Field(default_factory=list)


class RecommendedRoutinesData(BaseModel):
    items: list[RecommendedRoutineItem]
