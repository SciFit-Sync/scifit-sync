"""evidence_weight 산출 단위 테스트."""

from mlops.pipeline.evidence import (
    DEFAULT_WEIGHT,
    EVIDENCE_WEIGHTS,
    calculate_evidence_weight,
)


def test_meta_analysis_highest_weight():
    assert calculate_evidence_weight(["Meta-Analysis"]) == 1.00


def test_rct_weight():
    assert calculate_evidence_weight(["Randomized Controlled Trial"]) == 0.90


def test_multiple_types_picks_max():
    """가장 강한 등급 채택 (max 정책)."""
    types = ["Journal Article", "Randomized Controlled Trial"]
    assert calculate_evidence_weight(types) == 0.90


def test_unknown_type_returns_default():
    assert calculate_evidence_weight(["Some-Unknown-Type"]) == DEFAULT_WEIGHT


def test_empty_list_returns_default():
    assert calculate_evidence_weight([]) == DEFAULT_WEIGHT


def test_journal_article_only_fallback():
    """Journal Article만 있으면 0.50 fallback."""
    assert calculate_evidence_weight(["Journal Article"]) == 0.50


def test_known_tiers_present():
    """필수 publication type이 weight 테이블에 정의되어 있다."""
    required = [
        "Meta-Analysis",
        "Systematic Review",
        "Randomized Controlled Trial",
        "Clinical Trial",
        "Observational Study",
        "Cross-Sectional Study",
        "Review",
        "Case Reports",
        "Journal Article",
    ]
    for pt in required:
        assert pt in EVIDENCE_WEIGHTS


def test_weight_range():
    """모든 weight는 0.0~1.0 사이."""
    for pt, w in EVIDENCE_WEIGHTS.items():
        assert 0.0 <= w <= 1.0, f"{pt}: {w}"


def test_network_meta_analysis_tier1():
    """Network Meta-Analysis는 Meta-Analysis와 동급(1.0). 이전엔 미매핑으로 0.5 추락."""
    assert calculate_evidence_weight(["Network Meta-Analysis"]) == 1.00


def test_guideline_types_high_weight():
    """Practice Guideline / Guideline은 근거 종합 지침 → 0.85 (Journal Article 0.5보다 우선)."""
    assert calculate_evidence_weight(["Practice Guideline"]) == 0.85
    assert calculate_evidence_weight(["Guideline"]) == 0.85
    # max 정책: Journal Article(0.5)와 함께 와도 Guideline(0.85) 채택
    assert calculate_evidence_weight(["Journal Article", "Practice Guideline"]) == 0.85


def test_consensus_statement_weight():
    """Consensus Statement는 전문가 합의 → 0.70 (Journal Article보다 우선)."""
    assert calculate_evidence_weight(["Consensus Statement"]) == 0.70
    assert calculate_evidence_weight(["Journal Article", "Consensus Statement"]) == 0.70


def test_research_support_is_unmapped_funding_label():
    """Research Support는 연구 자금 라벨 — 근거강도 무관, 의도적 미매핑(0.5 유지)."""
    assert calculate_evidence_weight(["Research Support, Non-U.S. Gov't"]) == DEFAULT_WEIGHT
    # 실측상 항상 Journal Article과 동반 → max 정책상 0.5 유지
    assert calculate_evidence_weight(["Journal Article", "Research Support, N.I.H., Extramural"]) == 0.50


def test_scoping_review_weight():
    """Scoping Review는 근거 종합 리뷰 → 0.85 (Journal Article보다 우선, 0.5 탈출)."""
    assert calculate_evidence_weight(["Scoping Review"]) == 0.85
    assert calculate_evidence_weight(["Journal Article", "Scoping Review"]) == 0.85


def test_trial_variants_weight():
    """RCT 변형/단계·다기관 연구는 통제 실험 tier로 0.5 baseline을 넘는다."""
    assert calculate_evidence_weight(["Pragmatic Clinical Trial"]) == 0.85
    assert calculate_evidence_weight(["Clinical Trial, Phase III"]) == 0.85
    assert calculate_evidence_weight(["Journal Article", "Multicenter Study"]) == 0.65


def test_clinical_trial_protocol_downweighted():
    """Clinical Trial Protocol은 결과 미보고 → 0.30. generic JA가 더 이상 가리지 않는다(C)."""
    assert calculate_evidence_weight(["Clinical Trial Protocol"]) == 0.30
    assert calculate_evidence_weight(["Journal Article", "Clinical Trial Protocol"]) == 0.30


# ──────────────────────────────────────────────────────────────────────────────
# C: generic "Journal Article"(0.50)을 max 경쟁에서 제외하고 floor로만 사용.
# 거의 모든 PubMed 논문에 붙는 무정보 라벨이 더 약한 구체 type(Case Reports 0.30
# 등)을 max로 끌어올려 가리던 masking quirk 해소. 강한 type이 JA를 이기는 기존
# 동작은 그대로 유지된다.
# ──────────────────────────────────────────────────────────────────────────────


def test_journal_article_no_longer_masks_weaker_type():
    """generic JA(0.50)가 더 약한 구체 type을 가리지 않는다 (masking quirk 해소, C)."""
    assert calculate_evidence_weight(["Case Reports", "Journal Article"]) == 0.30
    assert calculate_evidence_weight(["Review", "Journal Article"]) == 0.40
    assert calculate_evidence_weight(["Editorial", "Journal Article"]) == 0.20


def test_journal_article_floor_preserved():
    """순수 JA / unknown 동반 JA는 0.50 floor 유지 (funding-label 논문 보호)."""
    assert calculate_evidence_weight(["Journal Article"]) == 0.50
    assert calculate_evidence_weight(["Journal Article", "Some-Unknown-Type"]) == 0.50


def test_strong_specific_type_still_wins_over_journal_article():
    """강한 구체 type은 기존대로 JA를 이긴다 (max 정책 유지)."""
    assert calculate_evidence_weight(["Randomized Controlled Trial", "Journal Article"]) == 0.90
    assert calculate_evidence_weight(["Journal Article", "Meta-Analysis"]) == 1.00


def test_equal_specific_type_keeps_050():
    """JA와 동일 가중(0.50) 구체 type이 와도 0.50 유지(하강 아님)."""
    assert calculate_evidence_weight(["Cross-Sectional Study", "Journal Article"]) == 0.50
