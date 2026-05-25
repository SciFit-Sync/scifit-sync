"""mlops.eval.run_eval 단위 테스트 — mock retriever만 사용 (ChromaDB 미접근)."""

import gzip
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from mlops.eval.run_eval import (
    GoldSetItem,
    _build_inmem_retriever,
    _load_embeddings_jsonl,
    aggregate,
    aggregate_by_category,
    evaluate_query,
    load_goldset,
    main,
    recall_at_k,
    reciprocal_rank,
    render_report,
    run_evaluation,
)


def _make_retriever(mapping: dict[str, list[dict]]):
    """질의 → 청크 리스트 매핑 기반 mock retriever."""

    def _retrieve(query: str, top_k: int) -> list[dict]:
        return mapping.get(query, [])[:top_k]

    return _retrieve


def _chunks(*pmids: str) -> list[dict]:
    return [{"pmid": p, "title": f"t-{p}", "section": "abstract", "score": 0.9} for p in pmids]


# ── recall_at_k ──────────────────────────────────────────


def test_recall_at_k_all_hit():
    assert recall_at_k(["A", "B"], ["A", "B", "C"], k=5) == 1.0


def test_recall_at_k_partial():
    assert recall_at_k(["A", "B"], ["A", "X", "Y"], k=5) == 0.5


def test_recall_at_k_no_hit():
    assert recall_at_k(["A", "B"], ["X", "Y", "Z"], k=5) == 0.0


def test_recall_at_k_respects_k_limit():
    # "B"가 6번째(idx 5)에 있음 → k=5에선 0.5, k=10에선 1.0
    retrieved = ["A", "X", "X", "X", "X", "B"]
    assert recall_at_k(["A", "B"], retrieved, k=5) == 0.5
    assert recall_at_k(["A", "B"], retrieved, k=10) == 1.0


def test_recall_at_k_empty_expected_returns_zero():
    assert recall_at_k([], ["A", "B"], k=5) == 0.0


def test_recall_at_k_ignores_empty_pmid_in_expected():
    # 빈 문자열 PMID는 expected에서 무시되어야
    assert recall_at_k(["", "A"], ["A"], k=5) == 1.0


# ── reciprocal_rank ──────────────────────────────────────


def test_mrr_first_position():
    assert reciprocal_rank(["A"], ["A", "B"]) == pytest.approx(1.0)


def test_mrr_third_position():
    assert reciprocal_rank(["A"], ["X", "Y", "A"]) == pytest.approx(1 / 3)


def test_mrr_no_hit():
    assert reciprocal_rank(["A"], ["X", "Y"]) == 0.0


def test_mrr_multi_expected_uses_first_hit():
    # "B"가 1위, "A"가 3위 → 첫 hit 기준이라 1.0
    assert reciprocal_rank(["A", "B"], ["B", "X", "A"]) == pytest.approx(1.0)


# ── evaluate_query ───────────────────────────────────────


def test_evaluate_query_full_pipeline():
    item = GoldSetItem(id="Q1", query="hypertrophy reps", category="programming", expected_pmids=("111",))
    retriever = _make_retriever({"hypertrophy reps": _chunks("111", "222", "333")})
    res = evaluate_query(item, retriever, top_k_values=(5, 10))
    assert res.retrieved_pmids == ["111", "222", "333"]
    assert res.recall[5] == 1.0
    assert res.recall[10] == 1.0
    assert res.mrr == pytest.approx(1.0)


def test_evaluate_query_deduplicates_pmids():
    # 같은 paper의 청크가 여러 개라도 paper-level로 한 번만 카운트
    item = GoldSetItem(id="Q1", query="q", category="c", expected_pmids=("B",))
    retriever = _make_retriever({"q": _chunks("A", "A", "B", "A")})
    res = evaluate_query(item, retriever, top_k_values=(2,))
    assert res.retrieved_pmids == ["A", "B"]
    assert res.recall[2] == 1.0


def test_evaluate_query_skips_empty_pmid():
    # 첫 청크는 pmid=""라 skip되어야
    item = GoldSetItem(id="Q1", query="q", category="c", expected_pmids=("A",))
    retriever = _make_retriever(
        {
            "q": [
                {"pmid": "", "title": "x", "section": "", "score": 0.9},
                {"pmid": "A", "title": "y", "section": "", "score": 0.8},
            ]
        }
    )
    res = evaluate_query(item, retriever, top_k_values=(5,))
    assert res.retrieved_pmids == ["A"]
    assert res.mrr == pytest.approx(1.0)


# ── aggregation ──────────────────────────────────────────


def test_aggregate_averages_metrics():
    item1 = GoldSetItem(id="Q1", query="q1", category="x", expected_pmids=("A",))
    item2 = GoldSetItem(id="Q2", query="q2", category="x", expected_pmids=("B",))
    retriever = _make_retriever(
        {
            "q1": _chunks("A"),  # recall@5=1.0, mrr=1.0
            "q2": _chunks("X"),  # recall@5=0.0, mrr=0.0
        }
    )
    results = run_evaluation([item1, item2], retriever, top_k_values=(5,))
    agg = aggregate(results, top_k_values=(5,))
    assert agg.n_queries == 2
    assert agg.recall[5] == pytest.approx(0.5)
    assert agg.mrr == pytest.approx(0.5)


def test_aggregate_by_category_separates_metrics():
    items = [
        GoldSetItem(id="Q1", query="q1", category="programming", expected_pmids=("A",)),
        GoldSetItem(id="Q2", query="q2", category="nutrition", expected_pmids=("B",)),
    ]
    retriever = _make_retriever({"q1": _chunks("A"), "q2": _chunks("X")})
    results = run_evaluation(items, retriever, top_k_values=(5,))
    by_cat = aggregate_by_category(results, top_k_values=(5,))
    assert by_cat["programming"].recall[5] == 1.0
    assert by_cat["nutrition"].recall[5] == 0.0


def test_aggregate_empty_returns_zero():
    agg = aggregate([], top_k_values=(5, 10))
    assert agg.n_queries == 0
    assert agg.recall[5] == 0.0
    assert agg.recall[10] == 0.0
    assert agg.mrr == 0.0


def test_run_evaluation_skips_failed_query():
    items = [
        GoldSetItem(id="Q1", query="ok", category="c", expected_pmids=("A",)),
        GoldSetItem(id="Q2", query="boom", category="c", expected_pmids=("B",)),
    ]

    def flaky(query: str, top_k: int) -> list[dict]:
        if query == "boom":
            raise RuntimeError("retriever down")
        return _chunks("A")

    results = run_evaluation(items, flaky, top_k_values=(5,))
    assert [r.item.id for r in results] == ["Q1"]


# ── load_goldset ─────────────────────────────────────────


def test_load_goldset_parses_jsonl(tmp_path: Path):
    p = tmp_path / "gs.jsonl"
    p.write_text(
        '{"id": "Q1", "query": "q1", "category": "programming", '
        '"expected_pmids": ["1", "2"], "notes": "n1"}\n'
        "\n"
        '{"id": "Q2", "query": "q2", "category": "nutrition", "expected_pmids": ["3"]}\n',
        encoding="utf-8",
    )
    items = load_goldset(p)
    assert len(items) == 2
    assert items[0].id == "Q1"
    assert items[0].expected_pmids == ("1", "2")
    assert items[0].notes == "n1"
    assert items[1].notes == ""


def test_load_goldset_raises_on_bad_json(tmp_path: Path):
    p = tmp_path / "bad.jsonl"
    p.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_goldset(p)


# ── render_report ────────────────────────────────────────


def test_render_report_contains_metrics_and_categories():
    items = [
        GoldSetItem(id="Q1", query="q1", category="programming", expected_pmids=("A",)),
        GoldSetItem(id="Q2", query="q2", category="nutrition", expected_pmids=("B",)),
    ]
    retriever = _make_retriever({"q1": _chunks("A"), "q2": _chunks("B")})
    results = run_evaluation(items, retriever, top_k_values=(5, 10))
    overall = aggregate(results, top_k_values=(5, 10))
    by_cat = aggregate_by_category(results, top_k_values=(5, 10))
    md = render_report(
        overall=overall,
        per_category=by_cat,
        goldset_path=Path("dummy.jsonl"),
        retriever_name="mock",
        top_k_values=(5, 10),
    )
    assert "recall@5" in md
    assert "recall@10" in md
    assert "MRR" in md
    assert "programming" in md
    assert "nutrition" in md
    assert "n=2" in md
    assert "mock" in md


# ── main CLI ─────────────────────────────────────────────


def test_main_writes_report(tmp_path: Path, monkeypatch):
    gs = tmp_path / "gs.jsonl"
    gs.write_text(
        '{"id": "Q1", "query": "q", "category": "programming", "expected_pmids": ["A"]}\n',
        encoding="utf-8",
    )
    out = tmp_path / "reports" / "out.md"

    def fake_retriever(query: str, top_k: int) -> list[dict]:
        return _chunks("A")

    # _build_chroma_retriever를 mock으로 교체 — 실제 ChromaDB/sentence-transformers 미접근
    monkeypatch.setattr("mlops.eval.run_eval._build_chroma_retriever", lambda: fake_retriever)

    rc = main(["--goldset", str(gs), "--output", str(out), "--top-k", "5", "10"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "recall@5" in text
    assert "recall@10" in text


def test_main_returns_error_on_empty_goldset(tmp_path: Path, monkeypatch):
    gs = tmp_path / "gs.jsonl"
    gs.write_text("\n\n", encoding="utf-8")
    out = tmp_path / "out.md"
    monkeypatch.setattr(
        "mlops.eval.run_eval._build_chroma_retriever",
        lambda: lambda q, k: [],
    )
    rc = main(["--goldset", str(gs), "--output", str(out)])
    assert rc == 1


# ── _load_embeddings_jsonl ──────────────────────────────────────────────


def _write_jsonl(path: Path, records: list[dict], use_gzip: bool = False) -> None:
    opener = gzip.open if use_gzip else open
    with opener(path, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r))
            f.write("\n")


def test_load_embeddings_jsonl_returns_matrix_and_metas(tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(
        p,
        [
            {"paper_pmid": "100", "paper_title": "t1", "embedding": [1.0, 0.0, 0.0, 0.0]},
            {"paper_pmid": "200", "paper_title": "t2", "embedding": [0.0, 1.0, 0.0, 0.0]},
        ],
    )
    matrix, metas = _load_embeddings_jsonl(p, expected_dim=4)
    assert matrix.shape == (2, 4)
    assert matrix.dtype == np.float32
    assert metas[0]["paper_pmid"] == "100"
    assert metas[1]["paper_pmid"] == "200"
    # embedding 키는 metas에서 제거되어야 함 (행렬과 중복 보관 방지)
    assert "embedding" not in metas[0]


def test_load_embeddings_jsonl_supports_gzip(tmp_path: Path):
    p = tmp_path / "emb.jsonl.gz"
    _write_jsonl(p, [{"paper_pmid": "X", "embedding": [1.0, 0.0]}], use_gzip=True)
    matrix, metas = _load_embeddings_jsonl(p, expected_dim=2)
    assert matrix.shape == (1, 2)
    assert metas[0]["paper_pmid"] == "X"


def test_load_embeddings_jsonl_raises_on_malformed_json(tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    p.write_text(
        '{"paper_pmid": "100", "embedding": [1, 0]}\nthis is not json\n{"paper_pmid": "200", "embedding": [0, 1]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid JSON"):
        _load_embeddings_jsonl(p, expected_dim=2)


def test_load_embeddings_jsonl_raises_on_missing_embedding_key(tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, [{"paper_pmid": "100"}])
    with pytest.raises(ValueError, match="missing 'embedding' key"):
        _load_embeddings_jsonl(p, expected_dim=4)


def test_load_embeddings_jsonl_raises_on_dim_mismatch(tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, [{"paper_pmid": "100", "embedding": [1.0, 0.0, 0.0]}])
    with pytest.raises(ValueError, match="dim mismatch"):
        _load_embeddings_jsonl(p, expected_dim=4)


def test_load_embeddings_jsonl_raises_on_empty(tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    p.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="임베딩이 한 줄도 없음"):
        _load_embeddings_jsonl(p, expected_dim=4)


def test_load_embeddings_jsonl_skips_blank_lines(tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    p.write_text(
        '{"paper_pmid": "100", "embedding": [1, 0]}\n\n{"paper_pmid": "200", "embedding": [0, 1]}\n',
        encoding="utf-8",
    )
    matrix, metas = _load_embeddings_jsonl(p, expected_dim=2)
    assert matrix.shape == (2, 2)


# ── _build_inmem_retriever (mock SentenceTransformer) ───────────────────


class _StubST:
    """결정론적 query 인코더 — 'want_<N>'에서 N번째 basis vector 반환."""

    last_encode_text: str | None = None
    last_normalize: bool | None = None

    def __init__(self, hf_name: str, device: str = "cpu", **kwargs):
        self.hf_name = hf_name
        self.device = device
        # dim은 hf_name으로 결정 (registry와 일치)
        dim_lookup = {
            "BAAI/bge-large-en-v1.5": 1024,
            "BAAI/bge-base-en-v1.5": 768,
            "pritamdeka/S-PubMedBert-MS-MARCO": 768,
        }
        self.dim = dim_lookup[hf_name]

    def encode(self, text, normalize_embeddings: bool = False):
        type(self).last_encode_text = text
        type(self).last_normalize = normalize_embeddings
        # 'want_K' 토큰이 들어있으면 basis vector e_K 반환 (이미 단위 길이)
        idx = 0
        for token in str(text).split():
            if token.startswith("want_"):
                try:
                    idx = int(token.split("_", 1)[1])
                except ValueError:
                    idx = 0
                break
        vec = np.zeros(self.dim, dtype=np.float32)
        vec[idx] = 1.0
        return vec


@pytest.fixture
def stub_sentence_transformers(monkeypatch):
    """sentence_transformers 모듈을 결정론적 stub로 교체."""
    _StubST.last_encode_text = None
    _StubST.last_normalize = None
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _StubST  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setenv("MLOPS_EMBED_DEVICE", "cpu")
    return _StubST


def _basis_corpus_for(dim: int, pmids: list[str]) -> list[dict]:
    """pmids[k] → e_k basis vector. 단위벡터이므로 dot==cosine."""
    records = []
    for k, pmid in enumerate(pmids):
        vec = [0.0] * dim
        vec[k] = 1.0
        records.append(
            {
                "paper_pmid": pmid,
                "paper_title": f"title-{pmid}",
                "section_name": "abstract",
                "embedding": vec,
            }
        )
    return records


def test_inmem_retriever_returns_results_in_cosine_order(stub_sentence_transformers, tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, _basis_corpus_for(dim=768, pmids=["A", "B", "C"]))
    retriever = _build_inmem_retriever(p, "bge-base")
    # query 'want_1' → e_1 → 가장 유사 pmid='B' (score=1.0), 나머지는 직교(score=0.0)
    res = retriever("want_1", top_k=3)
    assert res[0]["pmid"] == "B"
    assert res[0]["score"] == pytest.approx(1.0, abs=1e-6)
    # 나머지 두 개는 직교라 cosine=0 — 둘 사이의 상대 순서는 의미 없음
    assert {r["pmid"] for r in res[1:]} == {"A", "C"}
    for r in res[1:]:
        assert r["score"] == pytest.approx(0.0, abs=1e-6)


def test_inmem_retriever_orders_by_distinct_cosine_scores(stub_sentence_transformers, tmp_path: Path):
    """동률이 아닌 distinct 점수 케이스 — argsort descending 동작 검증."""
    # 각 corpus는 e_0과 다른 각도. query 'want_0' → e_0이므로 dot=row[0]값.
    p = tmp_path / "emb.jsonl"
    dim = 768

    # 단위벡터로 정규화된 청크 3개. e_0 성분이 큰 순서: C(0.9) > A(0.6) > B(0.2)
    def _make_unit(comp0: float, comp1: float) -> list[float]:
        v = np.zeros(dim, dtype=np.float32)
        v[0] = comp0
        v[1] = comp1
        v = v / np.linalg.norm(v)
        return v.tolist()

    records = [
        {"paper_pmid": "A", "paper_title": "tA", "embedding": _make_unit(0.6, 0.8)},
        {"paper_pmid": "B", "paper_title": "tB", "embedding": _make_unit(0.2, 0.98)},
        {"paper_pmid": "C", "paper_title": "tC", "embedding": _make_unit(0.9, 0.4359)},
    ]
    _write_jsonl(p, records)
    retriever = _build_inmem_retriever(p, "bge-base")
    res = retriever("want_0", top_k=3)
    assert [r["pmid"] for r in res] == ["C", "A", "B"]
    # 점수도 strictly descending
    assert res[0]["score"] > res[1]["score"] > res[2]["score"]


def test_inmem_retriever_respects_top_k(stub_sentence_transformers, tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, _basis_corpus_for(dim=768, pmids=["A", "B", "C", "D"]))
    retriever = _build_inmem_retriever(p, "bge-base")
    res = retriever("want_0", top_k=2)
    assert len(res) == 2
    assert res[0]["pmid"] == "A"


def test_inmem_retriever_prepends_bge_query_prefix(stub_sentence_transformers, tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, _basis_corpus_for(dim=768, pmids=["A", "B"]))
    retriever = _build_inmem_retriever(p, "bge-base")
    retriever("want_0", top_k=1)
    # BGE는 query 측에 prefix prepend
    assert _StubST.last_encode_text is not None
    assert _StubST.last_encode_text.startswith("Represent this sentence")
    assert "want_0" in _StubST.last_encode_text


def test_inmem_retriever_skips_prefix_for_pubmedbert(stub_sentence_transformers, tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, _basis_corpus_for(dim=768, pmids=["A", "B"]))
    retriever = _build_inmem_retriever(p, "pubmedbert-msmarco")
    retriever("want_0", top_k=1)
    # PubMedBERT는 symmetric — prefix 없음
    assert _StubST.last_encode_text == "want_0"


def test_inmem_retriever_passes_normalize_true_to_encoder(stub_sentence_transformers, tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, _basis_corpus_for(dim=768, pmids=["A"]))
    retriever = _build_inmem_retriever(p, "bge-base")
    retriever("want_0", top_k=1)
    assert _StubST.last_normalize is True


def test_inmem_retriever_returns_chunk_meta(stub_sentence_transformers, tmp_path: Path):
    p = tmp_path / "emb.jsonl"
    _write_jsonl(p, _basis_corpus_for(dim=768, pmids=["A"]))
    retriever = _build_inmem_retriever(p, "bge-base")
    res = retriever("want_0", top_k=1)
    assert res[0]["title"] == "title-A"
    assert res[0]["section"] == "abstract"


# ── main() with --retriever=inmem ──────────────────────────────────────


def test_main_inmem_writes_report(stub_sentence_transformers, tmp_path: Path):
    gs = tmp_path / "gs.jsonl"
    gs.write_text(
        '{"id": "Q1", "query": "want_0", "category": "programming", "expected_pmids": ["A"]}\n',
        encoding="utf-8",
    )
    emb = tmp_path / "emb.jsonl"
    _write_jsonl(emb, _basis_corpus_for(dim=768, pmids=["A", "B"]))
    out = tmp_path / "reports" / "out.md"

    rc = main(
        [
            "--goldset",
            str(gs),
            "--output",
            str(out),
            "--top-k",
            "5",
            "--retriever",
            "inmem",
            "--embeddings-file",
            str(emb),
            "--model-key",
            "bge-base",
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "inmem+bge-base" in text


def test_main_inmem_requires_embeddings_file(tmp_path: Path):
    gs = tmp_path / "gs.jsonl"
    gs.write_text(
        '{"id": "Q1", "query": "q", "category": "c", "expected_pmids": ["A"]}\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.md"
    with pytest.raises(SystemExit):
        main(
            [
                "--goldset",
                str(gs),
                "--output",
                str(out),
                "--retriever",
                "inmem",
                "--model-key",
                "bge-base",
            ]
        )


def test_main_inmem_requires_model_key(tmp_path: Path):
    gs = tmp_path / "gs.jsonl"
    gs.write_text(
        '{"id": "Q1", "query": "q", "category": "c", "expected_pmids": ["A"]}\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.md"
    emb = tmp_path / "emb.jsonl"
    _write_jsonl(emb, [{"paper_pmid": "A", "embedding": [1.0, 0.0]}])
    with pytest.raises(SystemExit):
        main(
            [
                "--goldset",
                str(gs),
                "--output",
                str(out),
                "--retriever",
                "inmem",
                "--embeddings-file",
                str(emb),
            ]
        )


def test_main_inmem_requires_existing_embeddings_file(tmp_path: Path):
    gs = tmp_path / "gs.jsonl"
    gs.write_text(
        '{"id": "Q1", "query": "q", "category": "c", "expected_pmids": ["A"]}\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.md"
    with pytest.raises(SystemExit):
        main(
            [
                "--goldset",
                str(gs),
                "--output",
                str(out),
                "--retriever",
                "inmem",
                "--embeddings-file",
                str(tmp_path / "missing.jsonl"),
                "--model-key",
                "bge-base",
            ]
        )
