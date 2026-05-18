"""RAG retrieval evidence_weight 가중치 정렬 단위 테스트 (Task 13)."""

from app.services.rag import (
    DEFAULT_EVIDENCE_WEIGHT,
    SIMILARITY_THRESHOLD,
    _rank_by_evidence_weight,
)


def test_high_weight_outranks_high_similarity():
    """약간 낮은 similarity여도 강한 evidence weight면 상위로 정렬된다."""
    raw = [
        {"distance": 0.20, "metadata": {"evidence_weight": 0.50}, "document": "obs"},
        {"distance": 0.25, "metadata": {"evidence_weight": 1.00}, "document": "meta"},
    ]
    ranked = _rank_by_evidence_weight(raw, similarity_threshold=0.0)
    # obs:  similarity 0.80 × 0.50 = 0.40
    # meta: similarity 0.75 × 1.00 = 0.75 → 1위
    assert ranked[0]["document"] == "meta"
    assert ranked[1]["document"] == "obs"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_threshold_uses_raw_similarity_not_score():
    """threshold는 raw similarity 기준 — 약한 weight 청크라도 강한 유사도면 통과한다."""
    raw = [
        {"distance": 0.20, "metadata": {"evidence_weight": 0.30}, "document": "weak_strong_sim"},
        {"distance": 0.40, "metadata": {"evidence_weight": 1.00}, "document": "strong_weak_sim"},
    ]
    # SIMILARITY_THRESHOLD = 0.70
    # weak_strong_sim:   similarity 0.80 → 통과 (가중 점수 0.24)
    # strong_weak_sim:   similarity 0.60 → 미달 (가중 점수가 0.60이어도 컷)
    ranked = _rank_by_evidence_weight(raw, similarity_threshold=SIMILARITY_THRESHOLD)
    docs = [r["document"] for r in ranked]
    assert "weak_strong_sim" in docs
    assert "strong_weak_sim" not in docs
    assert all(r["similarity"] >= SIMILARITY_THRESHOLD for r in ranked)


def test_missing_evidence_weight_uses_default():
    """metadata에 evidence_weight가 없으면 DEFAULT_EVIDENCE_WEIGHT(0.50) fallback."""
    raw = [{"distance": 0.10, "metadata": {}, "document": "no_weight"}]
    ranked = _rank_by_evidence_weight(raw, similarity_threshold=0.0)
    assert len(ranked) == 1
    assert ranked[0]["weight"] == DEFAULT_EVIDENCE_WEIGHT
    # similarity 0.90 × 0.50 = 0.45
    assert ranked[0]["score"] == 0.90 * DEFAULT_EVIDENCE_WEIGHT


def test_empty_results_returns_empty():
    """빈 입력 → 빈 출력."""
    assert _rank_by_evidence_weight([]) == []
    assert _rank_by_evidence_weight([], similarity_threshold=0.0) == []


def test_string_evidence_weight_in_metadata_converts_to_float():
    """ChromaDB metadata가 직렬화 과정에서 str로 들어와도 float로 안전 변환되어야 한다."""
    raw = [{"distance": 0.10, "metadata": {"evidence_weight": "0.75"}, "document": "x"}]
    ranked = _rank_by_evidence_weight(raw, similarity_threshold=0.0)
    assert ranked[0]["weight"] == 0.75
    # 0.90 × 0.75 = 0.675
    assert abs(ranked[0]["score"] - 0.675) < 1e-9


def test_none_metadata_falls_back_to_default_weight():
    """metadata=None 인 경우에도 크래시 없이 default weight로 처리된다."""
    raw = [{"distance": 0.10, "metadata": None, "document": "x"}]
    ranked = _rank_by_evidence_weight(raw, similarity_threshold=0.0)
    assert len(ranked) == 1
    assert ranked[0]["weight"] == DEFAULT_EVIDENCE_WEIGHT
