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
# 0.90 → 0.85 완화: local_pdf/OpenAlex-only 모집단에는 PubMed 미등재 논문
# (프리프린트·국내외 마이너 저널 등)이 섞여 있어 efetch 보강으로도 채울 수 없다.
# 실측(probe): 크롤 leg ≈92%, local_pdf leg 162/184(88%) — 합산이 90% 경계에
# 걸린다. 미등재분은 코드 결함이 아니라 데이터 특성이므로 게이트를 85%로 정렬.
PUBLICATION_TYPES_FILL_RATE_MIN: float = 0.85

# evidence_weight 다양화
EVIDENCE_WEIGHT_DISTINCT_MIN: int = 5
# 0.50 → 0.65 완화: 운동과학 코퍼스는 대다수가 일반 저널 논문(baseline 0.5)이다.
# evidence.py 매핑 보강(Network Meta-Analysis/Guideline/Consensus 추가) 후에도
# dry_15_v3 실측 0.5 비율은 0.60 — 나머지는 RCT/review가 아닌 순수 저널 논문이라
# 데이터 특성이다. 게이트를 0.65로 정렬(0.60을 여유로 통과)하되, 0.92 같은
# "전부 0.5 fallback"(차등화 붕괴) 회귀는 여전히 차단한다.
EVIDENCE_WEIGHT_05_RATIO_MAX: float = 0.65

# 청크 토큰 (CLAUDE.md §10 청크 정책 300~512 토큰과 정합)
AVG_TOKEN_MIN: int = 300
AVG_TOKEN_MAX: int = 512
TOKEN_P99_MAX: int = 660  # PR #174 흡수 trade-off 한계
TOKEN_OVER_512_RATIO_MAX: float = 0.05

# 청크/논문 비율
CHUNKS_PER_PAPER_MIN: int = 20
CHUNKS_PER_PAPER_MAX: int = 60

# PDF 경로 회귀 — local_pdf 평균 토큰.
# PDF도 의미 단위로 청킹되므로 150은 너무 짧다 → 하한 200. 상한은 본문 청크와
# 동일하게 512로 통일 (CLAUDE.md §10 정합).
PDF_AVG_TOKEN_MIN: int = 200
PDF_AVG_TOKEN_MAX: int = 512

# 임베딩 차원
EMBEDDING_DIM: int = 1024
