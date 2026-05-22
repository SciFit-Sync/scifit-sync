"""search_chunks 단위 테스트 — ChromaDB/BGE 의존을 mock으로 격리.

CLAUDE.md §13: search_chunks는 100% 커버리지 대상. 기존 test_rag_weight.py가
_rank_by_evidence_weight만 다루므로 search_chunks 진입 경로(공백 query / 정상
top_k / threshold 컷 / over-fetch 후 truncate / surrogate sanitize)를 보완.
"""

from unittest.mock import MagicMock

import pytest

from app.services import rag


@pytest.fixture
def patched_deps(monkeypatch):
    """search_chunks가 import 시점에 잡는 외부 의존을 monkeypatch.

    fake_collection을 반환하여 test 함수가 query() 응답을 시나리오별로 주입할 수 있다.
    """
    fake_model = MagicMock()
    fake_encoded = MagicMock()
    fake_encoded.tolist.return_value = [0.0] * 1024
    fake_model.encode.return_value = fake_encoded

    fake_collection = MagicMock()

    monkeypatch.setattr(rag, "_get_embed_model", lambda: fake_model)
    monkeypatch.setattr(rag, "_get_collection", lambda: fake_collection)
    return fake_collection


def test_search_chunks_empty_query_returns_empty(patched_deps):
    """공백/빈 query는 sanitize 단계에서 차단되어 ChromaDB 호출 없이 빈 list."""
    assert rag.search_chunks("") == []
    assert rag.search_chunks("   ") == []
    patched_deps.query.assert_not_called()


def test_search_chunks_normal_path_returns_ranked_topk(patched_deps):
    """정상 응답 → similarity × evidence_weight 가중 정렬 후 top_k 반환."""
    patched_deps.query.return_value = {
        "documents": [["doc A", "doc B"]],
        "metadatas": [
            [
                {
                    "paper_pmid": "1",
                    "paper_title": "TitleA",
                    "section_name": "Intro",
                    "evidence_weight": 1.0,
                },
                {
                    "paper_pmid": "2",
                    "paper_title": "TitleB",
                    "section_name": "Method",
                    "evidence_weight": 0.5,
                },
            ]
        ],
        "distances": [[0.10, 0.15]],
    }
    chunks = rag.search_chunks("squat hypertrophy", top_k=2)
    assert len(chunks) == 2
    # A: similarity 0.90 × 1.0 = 0.90, B: similarity 0.85 × 0.5 = 0.425 → A 우선
    assert chunks[0]["pmid"] == "1"
    assert chunks[0]["score"] > chunks[1]["score"]
    assert chunks[0]["title"] == "TitleA"
    assert chunks[0]["section"] == "Intro"


def test_search_chunks_filters_below_threshold(patched_deps):
    """SIMILARITY_THRESHOLD 미달 청크는 evidence_weight 가중에도 불구하고 필터링."""
    patched_deps.query.return_value = {
        "documents": [["weak"]],
        "metadatas": [[{"paper_pmid": "x", "paper_title": "T", "section_name": "S", "evidence_weight": 1.0}]],
        # raw similarity = 1 - 0.40 = 0.60, threshold 0.70 미달
        "distances": [[0.40]],
    }
    chunks = rag.search_chunks("query")
    assert chunks == []


def test_search_chunks_over_fetches_then_truncates_to_topk(patched_deps):
    """OVER_FETCH_MULTIPLIER로 많이 받아서 정렬 후 top_k만 반환."""
    n = 10
    patched_deps.query.return_value = {
        "documents": [[f"doc{i}" for i in range(n)]],
        "metadatas": [
            [
                {
                    "paper_pmid": str(i),
                    "paper_title": f"T{i}",
                    "section_name": "S",
                    "evidence_weight": 1.0,
                }
                for i in range(n)
            ]
        ],
        # 모두 threshold 통과: distances 0.10~0.19 → similarity 0.81~0.90
        "distances": [[0.10 + i * 0.01 for i in range(n)]],
    }
    chunks = rag.search_chunks("squat", top_k=3)
    assert len(chunks) == 3
    # n_results는 top_k * OVER_FETCH_MULTIPLIER로 호출됐어야 함
    call_kwargs = patched_deps.query.call_args.kwargs
    assert call_kwargs["n_results"] == 3 * rag.OVER_FETCH_MULTIPLIER


def test_search_chunks_sanitizes_surrogate_in_query(patched_deps):
    """lone surrogate(U+D800–U+DFFF)가 포함된 query도 sanitize 후 처리.

    sanitize 후 남은 텍스트가 비어있지 않으면 ChromaDB 호출이 일어난다.
    """
    bad = "스쿼트\ud83d"  # 한글 + lone high surrogate
    patched_deps.query.return_value = {
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    rag.search_chunks(bad)
    patched_deps.query.assert_called_once()
