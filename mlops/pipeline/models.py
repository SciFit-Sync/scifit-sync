"""파이프라인 데이터 모델 (Pydantic)."""

from pydantic import BaseModel


class PaperMeta(BaseModel):
    """PubMed 논문 메타데이터."""

    pmid: str
    title: str
    authors: str = ""
    journal: str = ""
    published_year: int | None = None
    doi: str = ""
    abstract: str = ""


class PaperSection(BaseModel):
    """논문 전문 섹션."""

    name: str  # e.g. "Introduction", "Methods", "Results", "Discussion"
    content: str


class PaperFull(BaseModel):
    """메타데이터 + 전문 섹션."""

    meta: PaperMeta
    sections: list[PaperSection] = []


class Chunk(BaseModel):
    """청킹 결과."""

    paper_pmid: str
    paper_title: str
    section_name: str
    chunk_index: int
    content: str
    token_count: int
