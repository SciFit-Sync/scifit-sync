"""Pre-Upsert Validation 임계값 모듈 (design §3.3.1).

운영 중 튜닝이 쉽도록 한 곳에 모음. 변경 시 design spec과 일치 유지.
"""

# 필수 키 (스키마) — 12개
REQUIRED_KEYS: tuple[str, ...] = (
    "chunk_index",
    "paper_pmid",
    "paper_title",
    "section_name",
    "token_count",
    "search_categories",
    "paper_doi",
    "publication_types",
    "evidence_weight",
    "fulltext_source",
    "published_year",
    "embedding",
)

# 식별자 fill rate — (paper_doi OR paper_pmid) 채워진 청크 비율
IDENTIFIER_FILL_RATE_MIN: float = 1.00  # 100% (만족 못하면 manifest 누수 버그)

# paper_doi 단독 fill rate (정보용)
PAPER_DOI_FILL_RATE_INFO_MIN: float = 0.99

# publication_types 비어있지 않은 비율 (design §1 C2)
PUBLICATION_TYPES_FILL_RATE_MIN: float = 0.90

# evidence_weight 다양화
EVIDENCE_WEIGHT_DISTINCT_MIN: int = 5
EVIDENCE_WEIGHT_05_RATIO_MAX: float = 0.50

# 청크 토큰
AVG_TOKEN_MIN: int = 300
AVG_TOKEN_MAX: int = 450
TOKEN_P99_MAX: int = 660  # PR #174 흡수 trade-off 한계
TOKEN_OVER_512_RATIO_MAX: float = 0.05

# 청크/논문 비율
CHUNKS_PER_PAPER_MIN: int = 20
CHUNKS_PER_PAPER_MAX: int = 60

# PDF 경로 회귀 — local_pdf 평균 토큰
PDF_AVG_TOKEN_MIN: int = 150
PDF_AVG_TOKEN_MAX: int = 250

# 임베딩 차원
EMBEDDING_DIM: int = 1024
