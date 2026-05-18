"""파이프라인 데이터 모델 (Pydantic)."""

from pydantic import BaseModel


class PaperMeta(BaseModel):
    """논문 메타데이터 (PubMed / PMC / OpenAlex 다중 소스)."""

    pmid: str
    title: str
    authors: str = ""
    journal: str = ""
    published_year: int | None = None
    doi: str = ""
    abstract: str = ""
    search_categories: list[str] = []
    # 다중 소스 식별자
    pmcid: str | None = None
    openalex_id: str | None = None
    # 증거 등급 메타
    publication_types: list[str] = []
    evidence_weight: float = 0.50
    # 전문 수집 출처 (e.g. "pmc_xml", "unpaywall", "semantic_scholar")
    fulltext_source: str | None = None


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
    search_categories: list[str] = []
    # 다중 소스 메타 (evidence_weight 정렬 + DOI dedup 준비)
    paper_doi: str = ""
    publication_types: list[str] = []
    evidence_weight: float = 0.50
    fulltext_source: str | None = None
    published_year: int | None = None
