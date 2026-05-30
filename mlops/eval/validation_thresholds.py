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
# 0.50 → 0.85 완화: 운동과학 코퍼스는 대다수가 일반 저널 논문(baseline 0.5)이다.
# evidence.py 매핑 보강(Network Meta-Analysis/Guideline/Consensus 추가) 후에도
# 순수 저널 논문이 다수라 0.5 비율은 데이터 특성이다. 게다가 이 비율은 수집
# depth가 깊어질수록 단조 상승한다 — 메타분석/RCT 등 고근거 논문은 얕은 depth에서
# 대부분 소진되고, 깊은 depth에는 근거등급 표기 없는 일반 저널 논문이 더 붙기
# 때문이다 (refeed_v2 실측: d010 0.61 → d020 0.63 → d030 0.65). 0.65는 dry(얕은)
# 기준이라 production 점증 적재(max-per-cat 200, ~10k)를 d030부터 오탐 차단했다.
# 차등화 자체는 정상(distinct 7~8값)이므로 0.85로 정렬하되, 0.92 같은
# "전부 0.5 fallback"(차등화 붕괴) 회귀는 distinct≥5 + 이 상한으로 여전히 차단한다.
EVIDENCE_WEIGHT_05_RATIO_MAX: float = 0.85

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
