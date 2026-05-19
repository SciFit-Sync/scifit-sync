"""RAG retrieval 자동 평가 스크립트.

골드셋(JSONL) → recall@5, recall@10, MRR 계산 → Markdown 리포트.

사용법:
    python -m mlops.eval.run_eval \
        --goldset mlops/eval/gold_set.jsonl \
        --output mlops/eval/reports/2026-05-19.md

테스트에서는 ``run_evaluation`` / ``main`` 에 mock retriever 콜러블을 주입한다.
"""

import argparse
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TOP_K_VALUES: tuple[int, ...] = (5, 10)
# chunk-level over-fetch 배율 — paper-level top_k 보장용 (server.search_chunks와 동일 컨셉).
DEFAULT_CHUNK_OVER_FETCH = 3

Retriever = Callable[[str, int], list[dict]]


@dataclass(frozen=True)
class GoldSetItem:
    """골드셋 한 줄 = 하나의 평가 질의."""

    id: str
    query: str
    category: str
    expected_pmids: tuple[str, ...]
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "GoldSetItem":
        return cls(
            id=str(raw["id"]),
            query=str(raw["query"]),
            category=str(raw["category"]),
            expected_pmids=tuple(str(p) for p in raw.get("expected_pmids", [])),
            notes=str(raw.get("notes", "")),
        )


@dataclass
class QueryResult:
    item: GoldSetItem
    retrieved_pmids: list[str]
    recall: dict[int, float]
    mrr: float


@dataclass
class AggregateMetrics:
    n_queries: int
    recall: dict[int, float]
    mrr: float


def load_goldset(path: Path) -> list[GoldSetItem]:
    """JSONL 골드셋을 로드한다. 빈 줄은 skip."""
    items: list[GoldSetItem] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON — {e}") from e
            items.append(GoldSetItem.from_dict(raw))
    return items


def recall_at_k(expected: Iterable[str], retrieved_pmids: list[str], k: int) -> float:
    """Set-based recall@k — 정답 중 top-k에 포함된 비율."""
    expected_set = {p for p in expected if p}
    if not expected_set:
        return 0.0
    top_k = set(retrieved_pmids[:k])
    return len(expected_set & top_k) / len(expected_set)


def reciprocal_rank(expected: Iterable[str], retrieved_pmids: list[str]) -> float:
    """첫 정답 위치의 역수. 정답 없으면 0.0."""
    expected_set = {p for p in expected if p}
    if not expected_set:
        return 0.0
    for rank, pmid in enumerate(retrieved_pmids, start=1):
        if pmid in expected_set:
            return 1.0 / rank
    return 0.0


def evaluate_query(
    item: GoldSetItem,
    retriever: Retriever,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    chunk_over_fetch: int = DEFAULT_CHUNK_OVER_FETCH,
) -> QueryResult:
    """단일 질의 평가. paper-level dedup (같은 PMID 중복 청크는 첫 위치만).

    chunk-level retriever에서 ``max(top_k_values) * chunk_over_fetch`` 만큼 over-fetch
    한 뒤 paper-level로 dedup 한다.
    """
    max_paper_k = max(top_k_values)
    chunks = retriever(item.query, max_paper_k * chunk_over_fetch)

    seen: set[str] = set()
    retrieved_pmids: list[str] = []
    for c in chunks:
        pmid = c.get("pmid") or ""
        if not pmid or pmid in seen:
            continue
        seen.add(pmid)
        retrieved_pmids.append(pmid)

    recalls = {k: recall_at_k(item.expected_pmids, retrieved_pmids, k) for k in top_k_values}
    mrr = reciprocal_rank(item.expected_pmids, retrieved_pmids)
    return QueryResult(item=item, retrieved_pmids=retrieved_pmids, recall=recalls, mrr=mrr)


def run_evaluation(
    goldset: list[GoldSetItem],
    retriever: Retriever,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    chunk_over_fetch: int = DEFAULT_CHUNK_OVER_FETCH,
) -> list[QueryResult]:
    """골드셋 전체에 대해 평가. 개별 질의 실패는 로그 + skip."""
    results: list[QueryResult] = []
    for item in goldset:
        try:
            res = evaluate_query(item, retriever, top_k_values, chunk_over_fetch)
        except Exception:
            logger.exception("질의 평가 실패 id=%s", item.id)
            continue
        results.append(res)
    return results


def aggregate(
    results: list[QueryResult],
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
) -> AggregateMetrics:
    if not results:
        return AggregateMetrics(n_queries=0, recall=dict.fromkeys(top_k_values, 0.0), mrr=0.0)
    n = len(results)
    recalls = {k: sum(r.recall[k] for r in results) / n for k in top_k_values}
    mrr = sum(r.mrr for r in results) / n
    return AggregateMetrics(n_queries=n, recall=recalls, mrr=mrr)


def aggregate_by_category(
    results: list[QueryResult],
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
) -> dict[str, AggregateMetrics]:
    bucket: dict[str, list[QueryResult]] = defaultdict(list)
    for r in results:
        bucket[r.item.category].append(r)
    return {cat: aggregate(items, top_k_values) for cat, items in bucket.items()}


def render_report(
    overall: AggregateMetrics,
    per_category: dict[str, AggregateMetrics],
    goldset_path: Path,
    retriever_name: str,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    timestamp: datetime | None = None,
) -> str:
    """Markdown 리포트 문자열을 생성한다."""
    ts = timestamp or datetime.now(tz=timezone.utc)
    k_headers = " | ".join(f"recall@{k}" for k in top_k_values)
    k_sep = " | ".join("---" for _ in top_k_values)

    lines: list[str] = [
        f"# RAG Retrieval 평가 리포트 ({ts.date()})",
        "",
        f"- 골드셋: `{goldset_path}` (n={overall.n_queries})",
        f"- Retriever: `{retriever_name}`",
        f"- 생성 시각 (UTC): {ts.isoformat(timespec='seconds')}",
        "",
        "## 전체 지표",
        "",
        f"| {k_headers} | MRR |",
        f"| {k_sep} | --- |",
    ]
    overall_cells = " | ".join(f"{overall.recall[k]:.3f}" for k in top_k_values)
    lines.append(f"| {overall_cells} | {overall.mrr:.3f} |")
    lines.append("")
    lines.append("## 카테고리별 지표")
    lines.append("")
    lines.append(f"| 카테고리 | n | {k_headers} | MRR |")
    lines.append(f"| --- | --- | {k_sep} | --- |")
    for cat in sorted(per_category.keys()):
        m = per_category[cat]
        cells = " | ".join(f"{m.recall[k]:.3f}" for k in top_k_values)
        lines.append(f"| {cat} | {m.n_queries} | {cells} | {m.mrr:.3f} |")
    lines.append("")
    return "\n".join(lines)


def _build_chroma_retriever() -> Retriever:
    """실제 ChromaDB 검색 retriever — 호출 시점에만 import (테스트에서는 monkeypatch)."""
    import os

    import chromadb
    from sentence_transformers import SentenceTransformer

    persist = os.environ.get("CHROMA_PERSIST_PATH", "/chroma-data")
    collection_name = os.environ.get("CHROMA_COLLECTION_NAME", "paper_chunks")
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
    instruction = "Represent this sentence for searching relevant passages: "

    client = chromadb.PersistentClient(path=persist)
    collection = client.get_collection(collection_name)
    model = SentenceTransformer(model_name)

    def _retrieve(query: str, top_k: int) -> list[dict]:
        vec = model.encode(instruction + query).tolist()
        res = collection.query(
            query_embeddings=[vec],
            n_results=top_k,
            include=["metadatas", "distances"],
        )
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        return [
            {
                "pmid": (m or {}).get("paper_pmid", ""),
                "title": (m or {}).get("paper_title", ""),
                "section": (m or {}).get("section_name", ""),
                "score": float(1.0 - d),
            }
            for m, d in zip(metas, dists, strict=False)
        ]

    return _retrieve


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="RAG retrieval 자동 평가")
    parser.add_argument("--goldset", type=Path, required=True, help="JSONL 골드셋 경로")
    parser.add_argument("--output", type=Path, required=True, help="Markdown 리포트 출력 경로")
    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        default=list(DEFAULT_TOP_K_VALUES),
        help="recall@k 슬라이스 (default: 5 10)",
    )
    parser.add_argument(
        "--retriever-name",
        type=str,
        default="chroma+bge-large-en-v1.5",
        help="리포트에 기록할 retriever 식별자",
    )
    args = parser.parse_args(argv)

    top_k_values = tuple(sorted(set(args.top_k)))

    goldset = load_goldset(args.goldset)
    if not goldset:
        logger.error("골드셋이 비어있다: %s", args.goldset)
        return 1
    logger.info("골드셋 로드 완료 n=%d", len(goldset))

    retriever = _build_chroma_retriever()
    results = run_evaluation(goldset, retriever, top_k_values)
    overall = aggregate(results, top_k_values)
    per_cat = aggregate_by_category(results, top_k_values)

    report = render_report(
        overall=overall,
        per_category=per_cat,
        goldset_path=args.goldset,
        retriever_name=args.retriever_name,
        top_k_values=top_k_values,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    logger.info("리포트 작성: %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
