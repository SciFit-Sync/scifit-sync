"""publication_types → evidence_weight 산출.

RAG retrieval 정렬에서 cosine_similarity × evidence_weight로 사용된다.
가장 강한 publication type 한 개의 weight를 채택한다 (max 정책).

운영 중 튜닝: 가중치 값 변경은 코드 1줄 + ChromaDB chunk 메타 백필로 반영.
"""

from __future__ import annotations

EVIDENCE_WEIGHTS: dict[str, float] = {
    # Tier 1: 종합 분석
    "Meta-Analysis": 1.00,
    "Network Meta-Analysis": 1.00,
    "Systematic Review": 1.00,
    "Scoping Review": 0.85,  # 근거 종합 리뷰 (systematic보다 포괄적·낮은 엄격성)
    # Tier 1.5: 근거 종합 지침 (다수 연구를 임상 권고로 종합)
    "Practice Guideline": 0.85,
    "Guideline": 0.85,
    "Consensus Statement": 0.70,
    # Tier 2: 통제된 실험 (RCT 및 그 변형/단계)
    "Randomized Controlled Trial": 0.90,
    "Pragmatic Clinical Trial": 0.85,  # 실세계 RCT 변형
    "Equivalence Trial": 0.85,
    "Adaptive Clinical Trial": 0.85,
    "Clinical Trial, Phase III": 0.85,
    "Clinical Trial, Phase IV": 0.80,
    "Controlled Clinical Trial": 0.80,
    "Clinical Trial, Phase II": 0.75,
    "Clinical Trial": 0.75,
    "Clinical Trial, Phase I": 0.65,
    "Multicenter Study": 0.65,  # 다기관 — 표본·일반화 보강
    "Comparative Study": 0.65,
    # Tier 3: 관찰
    "Cohort Study": 0.60,
    "Observational Study": 0.55,
    "Validation Study": 0.55,
    "Evaluation Study": 0.55,
    "Cross-Sectional Study": 0.50,
    "Case-Control Study": 0.50,
    # Tier 4: 약한 근거
    "Review": 0.40,
    "Narrative Review": 0.35,
    "Case Reports": 0.30,
    "Clinical Trial Protocol": 0.30,  # 프로토콜(결과 미보고) — 근거 약함
    "Editorial": 0.20,
    "Letter": 0.15,
    "Comment": 0.15,
    "News": 0.15,
    "Newspaper Article": 0.15,
    "Published Erratum": 0.15,
    "Retracted Publication": 0.10,
    # 일반 라벨 (다른 type이 없을 때만 적용)
    "Journal Article": 0.50,
    # NOTE: "Research Support, *" (N.I.H./Non-U.S. Gov't 등)는 연구 자금 출처
    # 라벨로 근거강도와 무관하므로 의도적으로 미매핑(0.5 baseline 유지)한다.
    # 실측상 항상 "Journal Article"과 동반 출현 → max 정책상 weight 영향 없음.
}

DEFAULT_WEIGHT: float = 0.50

# generic 라벨: 거의 모든 PubMed 논문에 붙는 무정보 type. 근거 강도 신호가
# 아니라 floor/fallback으로만 쓴다 (max 경쟁에서 제외해 더 약한 구체 type을
# 가리지 않게 한다 — masking quirk 해소).
GENERIC_TYPES: frozenset[str] = frozenset({"Journal Article"})


def calculate_evidence_weight(publication_types: list[str]) -> float:
    """가장 강한 '구체' publication type의 weight를 반환.

    generic 라벨("Journal Article")은 max 경쟁에서 제외하고 floor로만 쓴다.
    구체 type이 하나도 없고 generic만 있으면 generic의 floor(0.50)를,
    알려진 type이 전혀 없으면 DEFAULT_WEIGHT(0.50)를 반환한다.
    """
    specific = [EVIDENCE_WEIGHTS[pt] for pt in publication_types if pt in EVIDENCE_WEIGHTS and pt not in GENERIC_TYPES]
    if specific:
        return max(specific)
    if any(pt in GENERIC_TYPES for pt in publication_types):
        return EVIDENCE_WEIGHTS["Journal Article"]
    return DEFAULT_WEIGHT
