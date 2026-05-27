"""RAG retrieval 자동 평가 스크립트.

골드셋(JSONL) → recall@5, recall@10, MRR 계산 → Markdown 리포트.

사용법:
    python -m mlops.eval.run_eval \
        --goldset mlops/eval/gold_set.jsonl \
        --output mlops/eval/reports/2026-05-19.md

테스트에서는 ``run_evaluation`` / ``main`` 에 mock retriever 콜러블을 주입한다.
"""

import argparse
import gzip
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

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
    expected_dois: tuple[str, ...] = ()
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "GoldSetItem":
        return cls(
            id=str(raw["id"]),
            query=str(raw["query"]),
            category=str(raw["category"]),
            expected_pmids=tuple(str(p) for p in raw.get("expected_pmids", [])),
            expected_dois=tuple(str(d).lower() for d in raw.get("expected_dois", [])),
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
    """Set-based recall@k — 정답 중 top-k에 포함된 비율. (PMID-only 레거시)"""
    expected_set = {p for p in expected if p}
    if not expected_set:
        return 0.0
    top_k = set(retrieved_pmids[:k])
    return len(expected_set & top_k) / len(expected_set)


def _recall_at_k_union(expected_ids: set[str], retrieved_id_sets: list[set[str]], k: int) -> float:
    """PMID∪DOI union recall@k — 정답 PMID 또는 DOI 중 하나라도 매칭이면 hit."""
    if not expected_ids:
        return 0.0
    hits = 0
    for id_set in retrieved_id_sets[:k]:
        if expected_ids & id_set:
            hits += 1
    return min(hits, len(expected_ids)) / len(expected_ids)


def _mrr_union(expected_ids: set[str], retrieved_id_sets: list[set[str]]) -> float:
    """PMID∪DOI union MRR — 첫 hit의 역순위."""
    for rank, id_set in enumerate(retrieved_id_sets, start=1):
        if expected_ids & id_set:
            return 1.0 / rank
    return 0.0


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
    retrieved_dois: list[str] = []
    for c in chunks:
        pmid = c.get("pmid") or c.get("paper_pmid") or ""
        doi = (c.get("doi") or c.get("paper_doi") or "").lower()
        paper_key = doi or pmid
        if not paper_key or paper_key in seen:
            continue
        seen.add(paper_key)
        if pmid:
            seen.add(pmid)
        if doi:
            seen.add(doi)
        retrieved_pmids.append(pmid)
        retrieved_dois.append(doi)

    expected_ids = {p for p in item.expected_pmids if p} | {d for d in item.expected_dois if d}
    retrieved_ids = []
    for pmid, doi in zip(retrieved_pmids, retrieved_dois, strict=True):
        ids = {pmid, doi} - {""}
        retrieved_ids.append(ids)

    recalls = {k: _recall_at_k_union(expected_ids, retrieved_ids, k) for k in top_k_values}
    mrr_val = _mrr_union(expected_ids, retrieved_ids)
    return QueryResult(item=item, retrieved_pmids=retrieved_pmids, recall=recalls, mrr=mrr_val)


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


def _load_embeddings_jsonl(path: Path, expected_dim: int) -> tuple["np.ndarray", list[dict]]:
    """JSONL(.gz 허용) 임베딩 파일을 메모리 행렬 + 메타데이터로 로드한다.

    스트리밍 방식: Python float 리스트를 누적하지 않고 numpy 행에 직접 기록하여
    대규모 corpus(600K+ 청크)에서 OOM을 방지한다.
    """
    import numpy as np

    opener = gzip.open if path.suffix == ".gz" else open

    n_lines = 0
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n_lines += 1
    if n_lines == 0:
        raise ValueError(f"{path}: 임베딩이 한 줄도 없음")

    logger.info("inmem 로드: %s (%d rows, dim=%d)", path.name, n_lines, expected_dim)
    matrix = np.empty((n_lines, expected_dim), dtype=np.float32)
    metas: list[dict] = []
    row = 0
    with opener(path, "rt", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON — {e}") from e
            if "embedding" not in raw:
                raise ValueError(f"{path}:{line_no}: missing 'embedding' key")
            emb = raw.pop("embedding")
            if not isinstance(emb, list) or len(emb) != expected_dim:
                raise ValueError(
                    f"{path}:{line_no}: embedding dim mismatch — expected {expected_dim}, got {len(emb) if isinstance(emb, list) else type(emb).__name__}"
                )
            matrix[row] = emb
            metas.append(raw)
            row += 1
            if row % 100000 == 0:
                logger.info("inmem 로드: %d/%d rows", row, n_lines)
    if row != n_lines:
        logger.warning("inmem 로드: pass-1/pass-2 라인 수 불일치 (expected=%d, actual=%d)", n_lines, row)
    return matrix[:row], metas


DEFAULT_SHARD_SIZE = 50_000


def _iter_embedding_shards(
    path: Path,
    expected_dim: int,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> "Iterator[tuple[np.ndarray, list[dict]]]":
    """JSONL 임베딩 파일을 shard 단위로 스트리밍.

    OOM 방지: 전체 파일을 한 번에 로딩하지 않고 ``shard_size`` 줄씩 numpy 행렬로 변환해
    yield 한다. 이전 shard의 행렬은 caller가 참조를 놓으면 GC가 회수한다.
    """
    import numpy as np

    opener = gzip.open if path.suffix == ".gz" else open
    vectors: list[list[float]] = []
    metas: list[dict] = []
    with opener(path, "rt", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON — {e}") from e
            if "embedding" not in raw:
                raise ValueError(f"{path}:{line_no}: missing 'embedding' key")
            emb = raw.pop("embedding")
            if not isinstance(emb, list) or len(emb) != expected_dim:
                raise ValueError(
                    f"{path}:{line_no}: embedding dim mismatch — expected {expected_dim}, "
                    f"got {len(emb) if isinstance(emb, list) else type(emb).__name__}"
                )
            vectors.append(emb)
            metas.append(raw)
            if len(vectors) >= shard_size:
                yield np.asarray(vectors, dtype=np.float32), metas
                vectors, metas = [], []
    if vectors:
        yield np.asarray(vectors, dtype=np.float32), metas


def _build_inmem_retriever(
    embeddings_path: Path,
    model_key: str,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> Retriever:
    """소형 코퍼스용 — 전체 파일을 메모리에 올려서 빠르게 검색."""
    import numpy as np
    from mlops.pipeline.embedder import _get_model_by_spec
    from mlops.pipeline.specs import get_spec

    spec = get_spec(model_key)
    matrix, metas = _load_embeddings_jsonl(embeddings_path, expected_dim=spec.dim)

    if spec.normalize:
        norms = np.linalg.norm(matrix, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-3):
            raise ValueError(f"{embeddings_path}: corpus 벡터가 단위벡터가 아님 (mean_norm={float(norms.mean()):.4f})")

    model = _get_model_by_spec(spec)
    logger.info("inmem retriever: %d chunks loaded (model=%s)", len(metas), model_key)

    def _retrieve(query: str, top_k: int) -> list[dict]:
        q_text = (spec.query_prefix + query) if spec.query_prefix else query
        qvec = model.encode(q_text, normalize_embeddings=spec.normalize)
        qvec_arr = np.asarray(qvec, dtype=np.float32)
        scores = matrix @ qvec_arr
        top_idx = np.argsort(scores)[::-1][:top_k]
        return [
            {
                "pmid": metas[i].get("paper_pmid", ""),
                "doi": metas[i].get("paper_doi", ""),
                "paper_doi": metas[i].get("paper_doi", ""),
                "paper_pmid": metas[i].get("paper_pmid", ""),
                "title": metas[i].get("paper_title", ""),
                "section": metas[i].get("section_name", ""),
                "score": float(scores[i]),
            }
            for i in top_idx
        ]

    return _retrieve


def _run_shard_evaluation(
    embeddings_path: Path,
    model_key: str,
    goldset: list[GoldSetItem],
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    chunk_over_fetch: int = DEFAULT_CHUNK_OVER_FETCH,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> list[QueryResult]:
    """대형 코퍼스용 shard 기반 평가 — 파일 1회 순회, 전체 쿼리 batch 처리.

    shard마다 전체 질의를 한 번에 dot product하고, per-query top-k를 누적 병합한다.
    파일을 쿼리 수만큼 다시 읽지 않으므로 O(shards)로 끝난다.
    """
    import gc
    import heapq

    import numpy as np
    from mlops.pipeline.embedder import _get_model_by_spec
    from mlops.pipeline.specs import get_spec

    spec = get_spec(model_key)
    model = _get_model_by_spec(spec)

    max_paper_k = max(top_k_values)
    fetch_k = max_paper_k * chunk_over_fetch

    queries = [item.query for item in goldset]
    q_texts = [(spec.query_prefix + q) if spec.query_prefix else q for q in queries]
    q_matrix = np.asarray(
        model.encode(q_texts, normalize_embeddings=spec.normalize, show_progress_bar=True),
        dtype=np.float32,
    )
    logger.info("쿼리 %d개 인코딩 완료 (dim=%d)", len(queries), q_matrix.shape[1])

    per_query_heap: list[list[tuple[float, int, dict]]] = [[] for _ in goldset]
    tie_counter = 0

    for shard_idx, (matrix, metas) in enumerate(_iter_embedding_shards(embeddings_path, spec.dim, shard_size)):
        if shard_idx == 0 and spec.normalize:
            norms = np.linalg.norm(matrix, axis=1)
            if not np.allclose(norms, 1.0, atol=1e-3):
                raise ValueError(
                    f"{embeddings_path}: corpus 벡터가 단위벡터가 아님 (mean_norm={float(norms.mean()):.4f})"
                )

        all_scores = matrix @ q_matrix.T

        for qi in range(len(goldset)):
            scores = all_scores[:, qi]
            top_idx = np.argsort(scores)[::-1][:fetch_k]
            for i in top_idx:
                tie_counter += 1
                entry = (
                    float(scores[i]),
                    tie_counter,
                    {
                        "pmid": metas[i].get("paper_pmid", ""),
                        "doi": metas[i].get("paper_doi", ""),
                        "paper_doi": metas[i].get("paper_doi", ""),
                        "paper_pmid": metas[i].get("paper_pmid", ""),
                        "title": metas[i].get("paper_title", ""),
                        "section": metas[i].get("section_name", ""),
                        "score": float(scores[i]),
                    },
                )
                if len(per_query_heap[qi]) < fetch_k:
                    heapq.heappush(per_query_heap[qi], entry)
                elif entry[0] > per_query_heap[qi][0][0]:
                    heapq.heapreplace(per_query_heap[qi], entry)

        logger.info("shard %d 완료 (%d chunks)", shard_idx + 1, matrix.shape[0])
        del matrix, metas, all_scores
        gc.collect()

    results: list[QueryResult] = []
    for qi, item in enumerate(goldset):
        candidates = sorted(per_query_heap[qi], key=lambda x: x[0], reverse=True)
        chunks = [c[2] for c in candidates]

        seen: set[str] = set()
        retrieved_pmids: list[str] = []
        retrieved_dois: list[str] = []
        for c in chunks:
            pmid = c.get("pmid") or c.get("paper_pmid") or ""
            doi = (c.get("doi") or c.get("paper_doi") or "").lower()
            paper_key = doi or pmid
            if not paper_key or paper_key in seen:
                continue
            seen.add(paper_key)
            if pmid:
                seen.add(pmid)
            if doi:
                seen.add(doi)
            retrieved_pmids.append(pmid)
            retrieved_dois.append(doi)

        expected_ids = {p for p in item.expected_pmids if p} | {d for d in item.expected_dois if d}
        retrieved_ids = []
        for pmid, doi in zip(retrieved_pmids, retrieved_dois, strict=True):
            ids = {pmid, doi} - {""}
            retrieved_ids.append(ids)

        recalls = {k: _recall_at_k_union(expected_ids, retrieved_ids, k) for k in top_k_values}
        mrr_val = _mrr_union(expected_ids, retrieved_ids)
        results.append(QueryResult(item=item, retrieved_pmids=retrieved_pmids, recall=recalls, mrr=mrr_val))

    return results


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
        default=None,
        help="리포트에 기록할 retriever 식별자 (생략 시 retriever 모드에 따라 자동 결정)",
    )
    parser.add_argument(
        "--retriever",
        choices=["chroma", "inmem"],
        default="chroma",
        help="검색 백엔드. inmem=JSONL 직접 로드 cosine retriever (A/B 평가용)",
    )
    parser.add_argument(
        "--embeddings-file",
        type=Path,
        default=None,
        help="inmem retriever용 임베딩 JSONL(.gz) 경로 — --retriever=inmem 시 필수",
    )
    parser.add_argument(
        "--model-key",
        type=str,
        default=None,
        help="inmem retriever용 모델 key (registry 등록값) — --retriever=inmem 시 필수",
    )
    parser.add_argument(
        "--shard-size",
        type=int,
        default=DEFAULT_SHARD_SIZE,
        help=f"shard 기반 평가 시 shard 크기 (default: {DEFAULT_SHARD_SIZE}). 0이면 전체 로드 (소형 코퍼스용)",
    )
    args = parser.parse_args(argv)

    if args.retriever == "inmem":
        if args.embeddings_file is None or args.model_key is None:
            parser.error("--retriever=inmem 은 --embeddings-file 과 --model-key 가 필요합니다")
        if not args.embeddings_file.exists():
            parser.error(f"--embeddings-file 경로 없음: {args.embeddings_file}")

    top_k_values = tuple(sorted(set(args.top_k)))

    goldset = load_goldset(args.goldset)
    if not goldset:
        logger.error("골드셋이 비어있다: %s", args.goldset)
        return 1
    logger.info("골드셋 로드 완료 n=%d", len(goldset))

    if args.retriever == "inmem":
        use_shard = args.shard_size > 0 and args.embeddings_file.stat().st_size > 500_000_000
        if use_shard:
            logger.info("대형 코퍼스 감지 → shard 기반 평가 (shard_size=%d)", args.shard_size)
            results = _run_shard_evaluation(
                args.embeddings_file,
                args.model_key,
                goldset,
                top_k_values,
                shard_size=args.shard_size,
            )
            retriever_name = args.retriever_name or f"inmem+shard+{args.model_key}"
        else:
            retriever = _build_inmem_retriever(args.embeddings_file, args.model_key)
            retriever_name = args.retriever_name or f"inmem+{args.model_key}"
            results = run_evaluation(goldset, retriever, top_k_values)
    else:
        retriever = _build_chroma_retriever()
        retriever_name = args.retriever_name or "chroma+bge-large-en-v1.5"
        results = run_evaluation(goldset, retriever, top_k_values)

    overall = aggregate(results, top_k_values)
    per_cat = aggregate_by_category(results, top_k_values)

    report = render_report(
        overall=overall,
        per_category=per_cat,
        goldset_path=args.goldset,
        retriever_name=retriever_name,
        top_k_values=top_k_values,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    logger.info("리포트 작성: %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
