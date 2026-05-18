"""PaperChunk 모델 (ChromaDB의 Postgres 미러).

ChromaDB metadata와 evidence_weight, publication_types를 중복 보존해
RAG retrieval 시 SQL 조회에서도 동일한 가중치 정보를 활용한다.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PaperChunk(Base):
    __tablename__ = "paper_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(100), default=None)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer, default=None)

    # 신규: ChromaDB metadata와 중복 보존되는 근거 메타
    evidence_weight: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), default=None)
    publication_types: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)

    paper: Mapped["Paper"] = relationship(back_populates="chunks")  # noqa: F821
