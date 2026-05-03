import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ChatRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ChatRole] = mapped_column(
        Enum(ChatRole, native_enum=False, create_constraint=False, values_callable=lambda x: [e.value for e in x])
    )
    content: Mapped[str] = mapped_column(Text)
    paper_ids: Mapped[list | None] = mapped_column(JSONB, default=None)
    token_count: Mapped[int | None] = mapped_column(Integer, default=None)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    doi: Mapped[str | None] = mapped_column(String(200), unique=True, default=None)
    pmid: Mapped[str | None] = mapped_column(String(20), unique=True, default=None)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str] = mapped_column(Text)
    journal: Mapped[str] = mapped_column(String(300))
    year: Mapped[int]
    abstract: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, default=None)

    chunks: Mapped[list["PaperChunk"]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class PaperChunk(Base):
    __tablename__ = "paper_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int]
    section_name: Mapped[str | None] = mapped_column(String(100), default=None)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int]
    chroma_id: Mapped[str] = mapped_column(String(100))

    paper: Mapped["Paper"] = relationship(back_populates="chunks")
