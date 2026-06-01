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
    """Clinical Trial Protocol은 결과 미보고 → 0.30. max 정책상 Journal Article과 오면 0.5."""
    assert calculate_evidence_weight(["Clinical Trial Protocol"]) == 0.30
    assert calculate_evidence_weight(["Journal Article", "Clinical Trial Protocol"]) == 0.50
