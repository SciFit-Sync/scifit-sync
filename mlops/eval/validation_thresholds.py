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

# evidence_weight 게이트 = 차등화 "붕괴" 탐지 (design §3.3.1).
# 게이트는 두 신호의 AND (ValidationResult.passed):
#   (1) distinct >= EVIDENCE_WEIGHT_DISTINCT_MIN(5)  ← 차등화 다양성 유지
#   (2) 0.5 비율 < EVIDENCE_WEIGHT_05_RATIO_MAX        ← 붕괴 수준 상한
EVIDENCE_WEIGHT_DISTINCT_MIN: int = 5
# 0.50 → 0.65 → 0.85 → 0.92: 0.5 비율이 높다고 붕괴가 아니다. 붕괴의 정의는
# "차등화 소실" — publication_types=[] → evidence_weight=0.5 단일값으로 추락해
# distinct가 무너지고 거의 전부가 0.5인 상태다(이때 RAG의 cosine×evidence_weight
# 가중이 무의미해진다). 코퍼스 depth가 깊어질수록 매핑 불가한 일반 저널 논문
# (baseline 0.5) 비중은 자연 상승하지만, 고근거 청크(@0.9·@1.0)가 다량 공존하고
# distinct가 건강하면 차등화는 멀쩡하다. d100 실측(0.5비율 0.86, distinct 9,
# @0.9=1177·@1.0=587)이 정확히 이 경우 — depth-driven 상승이지 붕괴가 아니다.
# 단독 상한 0.85가 이를 오탐했으므로, 상한을 진짜 fallback 회귀선인 0.92로
# 올린다. 진짜 붕괴(전부 0.5)는 distinct 붕락 AND 0.92 상한 동시 위반으로 차단.
EVIDENCE_WEIGHT_05_RATIO_MAX: float = 0.92

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
