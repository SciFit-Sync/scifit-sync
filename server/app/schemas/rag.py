"""RAG ingest API 스키마 (Task 13).

mlops/scripts/initial_ingest.py:_build_payload 의 chunks payload와 1:1 대응.
Task 13 확장 필드: paper_doi, publication_types, evidence_weight,
fulltext_source, published_year.
"""

from pydantic import BaseModel, Field


class ChunkIngestPayload(BaseModel):
    """단일 청크 ingest payload — mlops `_build_payload`와 1:1 대응."""

    # 식별자
    paper_doi: str
    paper_pmid: str | None = ""
    paper_title: str
    # 청크 본문
    section_name: str
    chunk_index: int
    content: str
    token_count: int | None = None
    embedding: list[float]
    search_categories: list[str] = Field(default_factory=list)
    # Task 13 신규 필드
    publication_types: list[str] = Field(default_factory=list)
    evidence_weight: float = 0.50
    fulltext_source: str | None = ""
    published_year: int | None = 0


class RagIngestRequest(BaseModel):
    chunks: list[ChunkIngestPayload]
