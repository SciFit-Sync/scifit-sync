"""mlops.eval.run_eval 단위 테스트 — mock retriever만 사용 (ChromaDB 미접근)."""

from pathlib import Path

import pytest
from mlops.eval.run_eval import (
    GoldSetItem,
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
