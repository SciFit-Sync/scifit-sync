"""publication_types → evidence_weight 산출.

RAG retrieval 정렬에서 cosine_similarity × evidence_weight로 사용된다.
가장 강한 publication type 한 개의 weight를 채택한다 (max 정책).

운영 중 튜닝: 가중치 값 변경은 코드 1줄 + ChromaDB chunk 메타 백필로 반영.
"""

from __future__ import annotations

EVIDENCE_WEIGHTS: dict[str, float] = {
    # Tier 1: 종합 분석
    "Meta-Analysis":               1.00,
    "Systematic Review":           1.00,

    # Tier 2: 통제된 실험
    "Controlled Clinical Trial":   0.80,
    "Randomized Controlled Trial": 0.90,
    "Clinical Trial":              0.75,
    "Comparative Study":           0.65,

    # Tier 3: 관찰
    "Observational Study":         0.55,
    "Cross-Sectional Study":       0.50,
    "Cohort Study":                0.60,
    "Case-Control Study":          0.50,

    # Tier 4: 약한 근거
    "Review":                      0.40,
    "Narrative Review":            0.35,
    "Case Reports":                0.30,
    "Editorial":                   0.20,
    "Letter":                      0.15,
    "Comment":                     0.15,

    # 일반 라벨 (다른 type이 없을 때만 적용)
    "Journal Article":             0.50,
}

DEFAULT_WEIGHT: float = 0.50


def calculate_evidence_weight(publication_types: list[str]) -> float:
    """가장 강한 publication type의 weight를 반환.

    알려진 type 없으면 DEFAULT_WEIGHT (0.50).
    """
    weights = [EVIDENCE_WEIGHTS[pt] for pt in publication_types if pt in EVIDENCE_WEIGHTS]
    return max(weights, default=DEFAULT_WEIGHT)
