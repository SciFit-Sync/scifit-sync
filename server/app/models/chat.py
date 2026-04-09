import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ChatRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(300), default=None)
    started_at: Mapped[datetime] = mapped_column(server_default="now()")

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(TimestampMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[ChatRole]
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(50), default="text")
    routine_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_routines.id"), default=None
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("papers.id"), default=None)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
    paper: Mapped["Paper | None"] = relationship()


class Paper(TimestampMixin, Base):
    __tablename__ = "papers"

    doi: Mapped[str | None] = mapped_column(String(200), unique=True, default=None)
    pmid: Mapped[str | None] = mapped_column(String(20), unique=True, default=None)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str | None] = mapped_column(Text, default=None)
    journal: Mapped[str | None] = mapped_column(String(300), default=None)
    published_year: Mapped[int | None] = mapped_column(default=None)
    abstract: Mapped[str | None] = mapped_column(Text, default=None)

    chunks: Mapped[list["PaperChunk"]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class PaperChunk(TimestampMixin, Base):
    __tablename__ = "paper_chunks"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int]
    section_name: Mapped[str | None] = mapped_column(String(100), default=None)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(default=None)

    paper: Mapped["Paper"] = relationship(back_populates="chunks")
