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
        "Meta-Analysis", "Systematic Review",
        "Randomized Controlled Trial", "Clinical Trial",
        "Observational Study", "Cross-Sectional Study",
        "Review", "Case Reports", "Journal Article",
    ]
    for pt in required:
        assert pt in EVIDENCE_WEIGHTS


def test_weight_range():
    """모든 weight는 0.0~1.0 사이."""
    for pt, w in EVIDENCE_WEIGHTS.items():
        assert 0.0 <= w <= 1.0, f"{pt}: {w}"
