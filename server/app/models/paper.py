"""Paper 모델 (Phase 1 다중 소스 + evidence_weight).

이전: PMID primary lookup. 변경: DOI primary lookup (NOT NULL UNIQUE).
publication_types와 evidence_weight는 RAG retrieval 가중치 정렬에 사용된다.
fulltext_source는 본문 확보 경로(europe_pmc / pmc / openalex / abstract_only 등) 추적.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # 식별자
    doi: Mapped[str] = mapped_column(String(255), unique=True)
    pmid: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    pmcid: Mapped[str | None] = mapped_column(String(20), default=None)
    openalex_id: Mapped[str | None] = mapped_column(String(20), default=None, index=True)

    # 메타데이터
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str | None] = mapped_column(Text, default=None)
    journal: Mapped[str | None] = mapped_column(String(300), default=None)
    published_year: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    abstract: Mapped[str | None] = mapped_column(Text, default=None)

    # 근거 가중치
    publication_types: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'::text[]"))
    evidence_weight: Mapped[Decimal] = mapped_column(Numeric(3, 2), server_default=text("0.50"))

    # 본문 출처
    fulltext_source: Mapped[str] = mapped_column(String(20))

    # 카테고리
    search_categories: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'::text[]"))

    chunks: Mapped[list["PaperChunk"]] = relationship(  # noqa: F821
        back_populates="paper", cascade="all, delete-orphan"
    )
